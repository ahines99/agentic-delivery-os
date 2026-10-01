"""Three-stage scorer accounting; qualification alone never authorizes Docker spending."""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import (
    OVERHEAD_SECONDS,
    _guarded,
    _ledger_scope,
)
from agentic_delivery.execution.files import validate_files
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Stage = Literal["preflight", "acceptance", "regression"]
STAGES: tuple[Stage, ...] = ("preflight", "acceptance", "regression")


class ScoringFailure(ValueError):
    """Sanitized scoring authorization or uncertain-operation failure."""


class ScoringAuthorization(Contract):
    schema_version: Literal[1] = 1
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    qualification_artifact: Digest
    task_manifest_digest: Digest
    candidate_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    budget: Budget
    infrastructure_microdollars: int = Field(gt=0, strict=True, le=2**63 - 1)
    total_microdollars: int = Field(gt=0, strict=True, le=2**63 - 1)
    microdollars_per_second: int = Field(gt=0, strict=True, le=10**9)
    rate_card_version: NonEmpty = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")
    issued_at: AwareDatetime
    expires_at: AwareDatetime


@dataclass(frozen=True)
class _Context:
    task: HistoricalTask
    authority: QualificationAuthority
    artifacts: ArtifactStore
    grant: ScoringAuthorization
    grant_digest: str
    qualification_digest: str
    binding_digest: str
    protected_root: str
    output_root: str
    worker_root: str


def _require(condition: bool) -> None:
    if not condition:
        raise ScoringFailure("Scoring authority or operation binding is invalid")


class ScoringExecution:
    """Trusted scorer-owned boundary; use only after the harness's static candidate gates.

    A fresh account belongs to this exact candidate and grant. No model call, task
    admission, campaign allocation or semantic verdict is implemented here.
    """

    def __init__(
        self,
        *,
        ledger: EvaluationExecutionStore,
        authorization_provider: Callable[[], ScoringAuthorization],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ledger = ledger
        self.authorization_provider = authorization_provider
        self.clock = clock
        self._context: _Context | None = None

    def validate(
        self,
        task: HistoricalTask,
        candidate: dict[str, str],
        qualification_authority: QualificationAuthority,
        output_artifacts: ArtifactStore,
    ) -> None:
        """Bind current scoring authority and create bookkeeping; never start a runner."""
        try:
            _require(isinstance(qualification_authority, QualificationAuthority))
            task = HistoricalTask.model_validate(task.model_dump(mode="json"))
            validate_files(candidate)
            grant = ScoringAuthorization.model_validate(
                self.authorization_provider().model_dump(mode="json")
            )
            admitted = task.validate_qualification(
                qualification_authority.protected_artifacts,
                authority=qualification_authority,
                purpose="scoring",
            )
            _require(
                grant.account_id != admitted.account_id
                and grant.qualification_artifact == task.qualification_artifact
                and grant.task_manifest_digest
                == admitted.task_manifest_digest
                == qualification_task_digest(task.model_dump(mode="json"))
                and grant.candidate_digest == digest_json(candidate)
                and grant.budget == task.budget
                and len(task.acceptance_commands) == len(task.regression_commands) == 1
                and (255 + 2 * (grant.budget.command_seconds + OVERHEAD_SECONDS))
                * grant.microdollars_per_second
                <= min(grant.infrastructure_microdollars, grant.total_microdollars)
            )
            grant_digest = digest_json(grant.model_dump(mode="json"))
            qualification_digest = digest_json(admitted.model_dump(mode="json"))
            binding = {
                "schema_version": 1,
                "grant_digest": grant_digest,
                "task_digest": digest_json(task.model_dump(mode="json")),
                "candidate_digest": grant.candidate_digest,
                "qualification_digest": qualification_digest,
                "protected_root": str(qualification_authority.protected_artifacts.root.resolve()),
                "output_root": str(output_artifacts.root.resolve()),
                "worker_root": str(qualification_authority.worker_root.resolve()),
            }
            context = _Context(
                task=task,
                authority=qualification_authority,
                artifacts=output_artifacts,
                grant=grant,
                grant_digest=grant_digest,
                qualification_digest=qualification_digest,
                binding_digest=digest_json(binding),
                protected_root=str(qualification_authority.protected_artifacts.root.resolve()),
                output_root=str(output_artifacts.root.resolve()),
                worker_root=str(qualification_authority.worker_root.resolve()),
            )
            _require(
                self._context is None or self._context.binding_digest == context.binding_digest
            )
            self._guard(context)
            self.ledger.require_program_enrollment()
            self.ledger.create_account(
                grant.account_id,
                grant.budget,
                infrastructure_microdollars=grant.infrastructure_microdollars,
                total_microdollars=grant.total_microdollars,
            )
            artifact = output_artifacts.put(json.dumps(binding, sort_keys=True).encode())
            self.ledger.checkpoint(grant.account_id, "scoring-binding-v1", artifact)
            self._context = context
        except Exception:
            raise ScoringFailure("Scoring setup is unavailable or unauthorized") from None

    def _guard(self, context: _Context) -> None:
        grant, authority = context.grant, context.authority
        current = self.clock()
        _require(
            current.tzinfo is not None
            and current.utcoffset() is not None
            and grant.issued_at
            <= current
            < min(grant.expires_at, grant.issued_at + timedelta(seconds=grant.budget.wall_seconds))
            and digest_json(self.authorization_provider().model_dump(mode="json"))
            == context.grant_digest
            and str(authority.protected_artifacts.root.resolve()) == context.protected_root
            and str(context.artifacts.root.resolve()) == context.output_root
            and str(authority.worker_root.resolve()) == context.worker_root
        )
        settings = authority.settings_provider()
        repository = settings.repository(context.task.item.repository)
        _require(
            settings.admissions_enabled
            and repository.model_data_authorized
            and repository.sandbox_image == context.task.image
            and settings.execution_digest(repository.id) == grant.execution_config_digest
            and digest_json(authority.preparation_policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
            and all(
                value <= settings.budget.model_dump()[key]
                for key, value in grant.budget.model_dump().items()
            )
        )
        _scopes(authority.protected_artifacts.root, context.artifacts.root, authority.worker_root)
        for configured in settings.repositories:
            if configured.local_repository is not None:
                _scopes(
                    authority.protected_artifacts.root,
                    context.artifacts.root,
                    configured.local_repository,
                )
        _ledger_scope(settings, self.ledger, authority.worker_root)
        admitted = context.task.validate_qualification(
            authority.protected_artifacts, authority=authority, purpose="scoring"
        )
        _require(digest_json(admitted.model_dump(mode="json")) == context.qualification_digest)

    def operation_id(self, stage: Stage) -> str:
        _require(stage in STAGES and self._context is not None)
        assert self._context is not None
        return self._context.grant.account_id + ":scoring-" + stage

    async def run_operation(
        self,
        stage: Stage,
        work: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Reserve one stage, await execution and cleanup, or reuse an exact settled result."""
        try:
            _require(stage in STAGES and self._context is not None)
            context = self._context
            assert context is not None
            self._guard(context)
            grant = context.grant
            for previous in STAGES[: STAGES.index(stage)]:
                row = self.ledger.operation_receipt(grant.account_id, self.operation_id(previous))
                _require(row["status"] == "SETTLED")
            seconds = (
                255 if stage == "preflight" else grant.budget.command_seconds + OVERHEAD_SECONDS
            )
            operation_id = self.operation_id(stage)
            cached = self.ledger.reserve_infrastructure(
                grant.account_id,
                operation_id,
                max_seconds=seconds,
                microdollars_per_second=grant.microdollars_per_second,
                rate_card_version=grant.rate_card_version,
                binding_digest=digest_json({"scoring": context.binding_digest, "stage": stage}),
            )
            if cached is None:
                started = time.monotonic_ns()
                result = await _guarded(work(operation_id), lambda: self._guard(context))
                elapsed_ms = (time.monotonic_ns() - started + 999_999) // 1_000_000
                _require(isinstance(result, dict))
                self.ledger.settle_infrastructure(
                    operation_id,
                    elapsed_milliseconds=elapsed_ms,
                    result={"scoring_result": result},
                )
            row = self.ledger.operation_receipt(grant.account_id, operation_id)
            self._guard(context)
            _require(
                row["status"] == "SETTLED" and isinstance(row["result"]["scoring_result"], dict)
            )
            return dict(row["result"]["scoring_result"])
        except Exception:
            raise ScoringFailure(
                "Scoring operation stopped; inspect protected accounting"
            ) from None
