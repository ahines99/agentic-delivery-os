"""Concrete archived liabilities pinned before prospective registry creation."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore

Amount = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
AccountId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")]


class ProgramLegacyLiability(Contract):
    ledger_identity: Digest
    archive_authorization_digest: Digest
    archive_nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    accounting_digest: Digest
    account_ids: tuple[AccountId, ...] = Field(max_length=10000)
    settled_microdollars: Amount
    reserved_microdollars: Amount

    @property
    def liability_microdollars(self) -> int:
        return self.settled_microdollars + self.reserved_microdollars


class ProgramLegacyInventory(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["archived-program-liabilities"] = "archived-program-liabilities"
    ledgers: tuple[ProgramLegacyLiability, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def canonical(self) -> "ProgramLegacyInventory":
        identities = tuple(row.ledger_identity for row in self.ledgers)
        accounts = [account for row in self.ledgers for account in row.account_ids]
        if (
            identities != tuple(sorted(set(identities)))
            or len(accounts) != len(set(accounts))
            or any(row.account_ids != tuple(sorted(set(row.account_ids))) for row in self.ledgers)
        ):
            raise ValueError("Ambiguous archived program inventory")
        return self

    @property
    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))

    @property
    def liability_microdollars(self) -> int:
        return sum(row.liability_microdollars for row in self.ledgers)


@dataclass(frozen=True)
class ProgramLegacyContext:
    ledgers: Mapping[str, "EvaluationExecutionStore"]
    current_guard: Callable[[tuple[str, ...]], None]


def capture_program_legacy_inventory(*, context: ProgramLegacyContext) -> ProgramLegacyInventory:
    """Read exact concrete archived stores twice; submitted totals never establish capacity."""
    from agentic_delivery.evaluation.legacy_accounting import read_archived_ledger_accounting

    if type(context) is not ProgramLegacyContext:
        raise ValueError("Concrete archived ledger context required")
    ledgers = dict(context.ledgers)
    identities = tuple(sorted(ledgers))

    def guard() -> None:
        context.current_guard(identities)
        if dict(context.ledgers) != ledgers:
            raise ValueError("Archived ledger collection changed")

    def read() -> ProgramLegacyInventory:
        guard()
        rows = []
        for identity in identities:
            observed = read_archived_ledger_accounting(
                ledgers[identity], expected_ledger_identity=identity, current_guard=guard
            )
            totals = observed.accounting.totals
            rows.append(
                ProgramLegacyLiability(
                    ledger_identity=identity,
                    archive_authorization_digest=observed.binding.authorization_digest,
                    archive_nonce=observed.binding.nonce,
                    accounting_digest=observed.accounting_digest,
                    account_ids=observed.accounting.requested_account_ids,
                    settled_microdollars=totals.model_spent_microdollars
                    + totals.infrastructure_spent_microdollars,
                    reserved_microdollars=totals.model_reserved_microdollars
                    + totals.infrastructure_reserved_microdollars,
                )
            )
        guard()
        return ProgramLegacyInventory(ledgers=tuple(rows))

    original = read()
    if read() != original:
        raise ValueError("Archived ledger accounting changed")
    return original
