"""Reconcile prospective program envelopes with complete, metadata-only ledger snapshots."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    UsageTotals,
    _read_transaction,
    _snapshot_in_transaction,
)
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    program_account_states,
    program_binding,
)
from agentic_delivery.evaluation.program_budget import (
    ProgramAccountEnvelope,
    ProgramBudgetRegistry,
    ProgramBudgetSnapshot,
)
from agentic_delivery.evaluation.qualification import Digest


class ProgramAccountingFailure(ValueError):
    """Unavailable registry/ledger proof; never zero cost, release or replacement authority."""


def _require(condition: bool) -> None:
    if not condition:
        raise ProgramAccountingFailure("Current program accounting could not be reconstructed")


@dataclass(frozen=True)
class ProgramAccountingContext:
    registry: ProgramBudgetRegistry
    ledgers: Mapping[str, EvaluationExecutionStore]
    current_guard: Callable[[tuple[str, ...]], None]


class LocalProgramAccount(Contract):
    account_id: str
    state: Literal["OPEN", "CLOSED"]
    closed_microdollars: int | None = Field(strict=True, ge=0)


class ProgramLedgerView(Contract):
    registry_identity: Digest
    target_nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    accounting: AccountingSnapshot
    local_accounts: tuple[LocalProgramAccount, ...]


class ProgramAccountMatch(Contract):
    envelope: ProgramAccountEnvelope
    status: Literal["PENDING_CREATION", "PENDING_ACTIVATION", "ACTIVE", "CLOSURE_PENDING", "CLOSED"]
    observed_usage: UsageTotals | None


class ProgramAccountingReport(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["current-prospective-program-accounting"] = (
        "current-prospective-program-accounting"
    )
    registry: ProgramBudgetSnapshot
    ledgers: tuple[ProgramLedgerView, ...]
    accounts: tuple[ProgramAccountMatch, ...]
    observed_totals: UsageTotals
    pending_creation: int = Field(strict=True, ge=0)
    pending_activation: int = Field(strict=True, ge=0)
    pending_closure: int = Field(strict=True, ge=0)
    all_approved_targets_enrolled: bool = Field(strict=True)
    all_envelopes_closed: bool = Field(strict=True)
    # Registry envelopes and observed ledger usage overlap; never add them together.
    historical_costs_included: Literal[False] = False
    complete_program_cost: Literal[False] = False
    distributed_atomic_snapshot: Literal[False] = False
    model_results_read: Literal[False] = False
    ledger_mutations: Literal[False] = False
    execution_authorized: Literal[False] = False


def _ledger_view(
    store: EvaluationExecutionStore,
    identity: str,
    registry: ProgramBudgetSnapshot,
    guard: Callable[[], None],
) -> ProgramLedgerView:
    guard()
    _require(type(store) is EvaluationExecutionStore and store.program_bound)
    _require(ledger_target_identity(store) == identity)
    with _read_transaction(store) as connection:
        binding = connection.execute(
            select(
                program_binding.c.id,
                program_binding.c.registry_identity,
                program_binding.c.target_nonce,
            )
        ).all()
        _require(
            binding == [("program", registry.registry_identity, registry.target_nonces[identity])]
        )
        accounting = _snapshot_in_transaction(
            store,
            connection,
            expected_ledger_identity=identity,
            account_ids=None,
            current_guard=guard,
        )
        rows = (
            connection.execute(
                select(
                    program_account_states.c.account_id,
                    program_account_states.c.state,
                    program_account_states.c.closed_microdollars,
                )
                .order_by(program_account_states.c.account_id)
                .limit(10001)
            )
            .mappings()
            .all()
        )
        _require(len(rows) <= 10000)
        local = tuple(LocalProgramAccount.model_validate(dict(row)) for row in rows)
        _require(tuple(row.account_id for row in local) == accounting.requested_account_ids)
        _require(ledger_target_identity(store) == identity)
        guard()
    return ProgramLedgerView(
        registry_identity=registry.registry_identity,
        target_nonce=registry.target_nonces[identity],
        accounting=accounting,
        local_accounts=local,
    )


def _match(
    registry: ProgramBudgetSnapshot, views: tuple[ProgramLedgerView, ...]
) -> tuple[ProgramAccountMatch, ...]:
    actual = {
        (view.accounting.ledger_identity, account.account_id): (account, state)
        for view in views
        for account, state in zip(view.accounting.accounts, view.local_accounts, strict=True)
    }
    expected = {(e.ledger_identity, e.account_id) for e in registry.envelopes}
    _require(not actual.keys() - expected)
    result = []
    for envelope in registry.envelopes:
        pair = actual.get((envelope.ledger_identity, envelope.account_id))
        if pair is None:
            _require(envelope.state == "HELD")
            result.append(
                ProgramAccountMatch(
                    envelope=envelope, status="PENDING_CREATION", observed_usage=None
                )
            )
            continue
        account, local = pair
        _require(account.budget_digest == envelope.budget_digest)
        totals = account.totals
        spent = totals.model_spent_microdollars + totals.infrastructure_spent_microdollars
        reserved = totals.model_reserved_microdollars + totals.infrastructure_reserved_microdollars
        _require(spent + reserved <= envelope.ceiling_microdollars)
        status: Literal["PENDING_ACTIVATION", "ACTIVE", "CLOSURE_PENDING", "CLOSED"]
        if local.state == "OPEN":
            _require(local.closed_microdollars is None and envelope.state != "CLOSED")
            if envelope.state == "HELD":
                _require(not account.operations and totals == UsageTotals())
                status = "PENDING_ACTIVATION"
            else:
                status = "ACTIVE"
        else:
            _require(
                local.closed_microdollars == spent and totals.unresolved_operations == reserved == 0
            )
            _require(envelope.state in {"ACTIVE", "CLOSED"})
            if envelope.state == "CLOSED":
                _require(envelope.closed_microdollars == spent)
                status = "CLOSED"
            else:
                status = "CLOSURE_PENDING"
        result.append(ProgramAccountMatch(envelope=envelope, status=status, observed_usage=totals))
    return tuple(result)


def reconcile_program_accounting(*, context: ProgramAccountingContext) -> ProgramAccountingReport:
    """Concrete reads only, no repair, ledger writes, provider calls or private payload access."""
    try:
        _require(
            type(context) is ProgramAccountingContext
            and type(context.registry) is ProgramBudgetRegistry
        )
        ledgers = dict(context.ledgers)
        identities = tuple(sorted(ledgers))

        def guard() -> None:
            _require(dict(context.ledgers) == ledgers)
            context.current_guard(identities)

        guard()
        registry = context.registry.snapshot()
        _require(identities == registry.bound_ledger_identities)

        def read() -> tuple[ProgramLedgerView, ...]:
            result = []
            operations = accounts = 0
            for identity in identities:
                view = _ledger_view(ledgers[identity], identity, registry, guard)
                accounts += len(view.accounting.accounts)
                operations += sum(len(a.operations) for a in view.accounting.accounts)
                _require(accounts <= 10000 and operations <= 100000)
                result.append(view)
            return tuple(result)

        views = read()
        accounts = _match(registry, views)
        repeated = read()
        exclude = {"accounting": {"observed_at"}}
        _require(
            [v.model_dump(exclude=exclude) for v in views]
            == [v.model_dump(exclude=exclude) for v in repeated]
        )
        _require(context.registry.snapshot() == registry)
        guard()
        totals = UsageTotals.model_validate(
            {
                field: sum(getattr(v.accounting.totals, field) for v in repeated)
                for field in UsageTotals.model_fields
            }
        )
        return ProgramAccountingReport(
            registry=registry,
            ledgers=repeated,
            accounts=accounts,
            observed_totals=totals,
            pending_creation=sum(row.status == "PENDING_CREATION" for row in accounts),
            pending_activation=sum(row.status == "PENDING_ACTIVATION" for row in accounts),
            pending_closure=sum(row.status == "CLOSURE_PENDING" for row in accounts),
            all_approved_targets_enrolled=set(identities)
            == set(registry.policy.approved_ledger_identities),
            all_envelopes_closed=bool(accounts) and all(row.status == "CLOSED" for row in accounts),
        )
    except Exception:
        raise ProgramAccountingFailure(
            "Current program accounting could not be reconstructed"
        ) from None
