"""Metered owned semantic examples; actual checks, never historical admission or calibration."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from agentic_delivery.agents.evidence import ExecutionReceipt, Preflight
from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.execution_store import (
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import (
    OVERHEAD_SECONDS,
    PREFLIGHT_CHECKS,
    _guarded,
    validate_execution,
)
from agentic_delivery.evaluation.semantic_examples import SemanticSubject
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import validate_files
from agentic_delivery.execution.verification import verify
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

STAGES = ("preflight", "acceptance", "regression")


class SemanticPreparationFailure(ValueError):
    """Private preparation is missing, unauthorized or uncertain."""


class OwnedSemanticRequest(Contract):
    schema_version: Literal[1] = 1
    purpose: Literal["OWNED_DEVELOPMENT_CALIBRATION"] = "OWNED_DEVELOPMENT_CALIBRATION"
    subject_artifact: Digest
    image: str = Field(pattern=r"^(?:[A-Za-z0-9._/:~-]+@)?sha256:[a-f0-9]{64}$")


class OwnedSemanticAuthorization(Contract):
    schema_version: Literal[1] = 1
    account_id: str = Field(pattern=r"^owned-semantic:[a-f0-9]{32}$")
    request_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    command_seconds: int = Field(strict=True, ge=1, le=600)
    wall_seconds: int = Field(strict=True, ge=1, le=1800)
    infrastructure_microdollars: int = Field(strict=True, ge=1, le=1_000_000)
    microdollars_per_second: int = Field(strict=True, ge=1, le=1_000_000)
    rate_card_version: NonEmpty

    @model_validator(mode="after")
    def finite(self) -> "OwnedSemanticAuthorization":
        maximum = 255 + 2 * (self.command_seconds + OVERHEAD_SECONDS)
        if (
            self.issued_at >= self.expires_at
            or maximum * self.microdollars_per_second > self.infrastructure_microdollars
        ):
            raise ValueError("Owned execution must reserve its complete finite three-stage ceiling")
        return self


class OwnedSemanticPolicy(Contract):
    """Current trusted allowlist of exact finite grants, not an authored subject field."""

    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    approved_authorization_digests: tuple[Digest, ...] = Field(min_length=1, max_length=32)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class OwnedSemanticExecution(Contract):
    schema_version: Literal[1] = 1
    status: Literal["EXECUTED_NOT_CALIBRATED"] = "EXECUTED_NOT_CALIBRATED"
    purpose: Literal["OWNED_DEVELOPMENT_CALIBRATION"] = "OWNED_DEVELOPMENT_CALIBRATION"
    admitted: Literal[False] = False
    baseline_executed: Literal[False] = False
    model_calls: Literal[0] = 0
    account_id: NonEmpty
    request_digest: Digest
    authorization_digest: Digest
    binding_artifact: Digest
    subject_artifact: Digest
    candidate_digest: Digest
    executed_snapshot_digest: Digest
    preflight_artifact: Digest
    acceptance_artifact: Digest
    regression_artifact: Digest
    operation_receipt_digests: tuple[Digest, ...] = Field(min_length=3, max_length=3)
    infrastructure_microdollars: int = Field(strict=True, ge=0)


def _require(value: bool) -> None:
    if not value:
        raise SemanticPreparationFailure(
            "Owned semantic execution authority or evidence is invalid"
        )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _read(artifacts: ArtifactStore, digest: str) -> Any:
    return json.loads(artifacts.get(digest), object_pairs_hook=_pairs)


def _put(artifacts: ArtifactStore, value: Any) -> str:
    document = value.model_dump(mode="json") if isinstance(value, Contract) else value
    return artifacts.put(json.dumps(document, sort_keys=True, allow_nan=False).encode())


def _budget(grant: OwnedSemanticAuthorization) -> Budget:
    return Budget(
        model_microdollars=1,
        input_tokens=1,
        output_tokens=1,
        wall_seconds=grant.wall_seconds,
        command_seconds=grant.command_seconds,
        repair_rounds=0,
    )


def _time(value: Any) -> datetime:
    _require(isinstance(value, str))
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return parsed


def owned_semantic_commands() -> tuple[CommandProfile, CommandProfile]:
    """The fixed owned module profile; no caller-selected shell or test flags."""

    def command(stage: str, node: str) -> CommandProfile:
        return CommandProfile(
            id=stage,
            argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", node),
            expected_tests=1,
        )

    return (
        command("acceptance", "tests/test_batches.py::test_examples"),
        command("regression", "tests/test_existing.py::test_input_unchanged"),
    )


class OwnedSemanticRuntime:
    """Controller-owned preparation with exact grants and a read-only evidence consumer.

    This boundary accepts original authored subjects, not HistoricalTask records. It
    never loads expectations, constructs model inputs, or invokes a model provider.
    """

    def __init__(
        self,
        *,
        subject_artifacts: ArtifactStore,
        output_artifacts: ArtifactStore,
        worker_root: Path,
        ledger: EvaluationExecutionStore,
        authorization_provider: Callable[[], OwnedSemanticAuthorization],
        policy_provider: Callable[[], OwnedSemanticPolicy],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.subject_artifacts = subject_artifacts
        self.output_artifacts = output_artifacts
        self.worker_root = worker_root
        self.ledger = ledger
        self.authorization_provider = authorization_provider
        self.policy_provider = policy_provider
        self.clock = clock

    def _inputs(
        self,
        request: OwnedSemanticRequest,
        *,
        active: bool,
    ) -> tuple[OwnedSemanticAuthorization, SemanticSubject, dict[str, str], str]:
        request = OwnedSemanticRequest.model_validate(request.model_dump(mode="json"))
        grant = OwnedSemanticAuthorization.model_validate(
            self.authorization_provider().model_dump(mode="json")
        )
        policy = OwnedSemanticPolicy.model_validate(self.policy_provider().model_dump(mode="json"))
        now = self.clock()
        _require(
            now.tzinfo is not None
            and now.utcoffset() is not None
            and policy.enabled
            and policy.issued_at <= now < policy.expires_at
            and digest_json(grant.model_dump(mode="json")) in policy.approved_authorization_digests
            and grant.request_digest == digest_json(request.model_dump(mode="json"))
        )
        if active:
            _require(grant.issued_at <= now < self._deadline(grant))
        _scopes(self.subject_artifacts.root, self.output_artifacts.root, self.worker_root)
        if self.ledger.sqlite:
            database = self.ledger.engine.url.database
            _require(database is not None and database != ":memory:")
            assert database is not None
            _require(not Path(database).resolve().is_relative_to(self.worker_root.resolve()))
        subject = SemanticSubject.model_validate(
            _read(self.subject_artifacts, request.subject_artifact)
        )
        candidate = {
            subject.module_path: subject.candidate_source,
            subject.regression_path: subject.regression_source,
        }
        files = {**candidate, subject.oracle_path: subject.oracle_source}
        validate_files(files)
        binding = self._binding_document(request, grant, subject, files)
        # ArtifactStore uses the same canonical serialization in _put below.

        binding_ref = hashlib.sha256(
            json.dumps(binding, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        return grant, subject, files, binding_ref

    @staticmethod
    def _deadline(grant: OwnedSemanticAuthorization) -> datetime:
        return min(grant.expires_at, grant.issued_at + timedelta(seconds=grant.wall_seconds))

    def _binding_document(
        self,
        request: OwnedSemanticRequest,
        grant: OwnedSemanticAuthorization,
        subject: SemanticSubject,
        files: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "request": request.model_dump(mode="json"),
            "authorization_digest": digest_json(grant.model_dump(mode="json")),
            "subject_root": str(self.subject_artifacts.root.resolve()),
            "output_root": str(self.output_artifacts.root.resolve()),
            "worker_root": str(self.worker_root.resolve()),
            "candidate_digest": digest_json(
                {
                    subject.module_path: subject.candidate_source,
                    subject.regression_path: subject.regression_source,
                }
            ),
            "executed_snapshot_digest": digest_json(files),
        }

    def _account(self, grant: OwnedSemanticAuthorization, binding_ref: str) -> None:
        account = self.ledger.account(grant.account_id)
        expected = _budget(grant).model_dump(mode="json")
        expected[INFRA_TERMS] = {
            "schema_version": 1,
            "infrastructure_microdollars": grant.infrastructure_microdollars,
            "total_microdollars": grant.infrastructure_microdollars,
        }
        _require(account["budget"] == expected)
        checkpoint = self.ledger.checkpoint_receipt(grant.account_id, "owned-semantic-binding-v1")
        _require(checkpoint is not None and checkpoint["artifact_digest"] == binding_ref)
        assert checkpoint is not None
        _require(
            grant.issued_at <= _time(checkpoint["created_at"]) < self._deadline(grant)
            and _time(account["created_at"]) <= _time(checkpoint["created_at"]) <= self.clock()
        )
        _read(self.output_artifacts, binding_ref)
        _require(
            account["model_reserved_microdollars"] == account["model_spent_microdollars"] == 0
            and account["input_tokens"] == account["output_tokens"] == 0
        )
        with self.ledger.engine.connect() as connection:
            ids: set[str] = set(
                connection.scalars(
                    select(operations.c.id).where(operations.c.account_id == grant.account_id)
                )
            )
        _require(ids <= {grant.account_id + ":" + stage for stage in STAGES})

    def _operation(
        self,
        request: OwnedSemanticRequest,
        grant: OwnedSemanticAuthorization,
        files: dict[str, str],
        binding_ref: str,
        stage: str,
    ) -> tuple[dict[str, Any], str, str | None]:
        row = self.ledger.operation_receipt(grant.account_id, grant.account_id + ":" + stage)
        seconds = 255 if stage == "preflight" else grant.command_seconds + OVERHEAD_SECONDS
        terms = {
            "schema_version": 1,
            "kind": "infrastructure",
            "max_seconds": seconds,
            "microdollars_per_second": grant.microdollars_per_second,
            "rate_card_version": grant.rate_card_version,
            "binding_digest": digest_json({"binding": binding_ref, "stage": stage}),
        }
        _require(
            row["status"] == "SETTLED"
            and row.get("operation_kind") == "infrastructure"
            and row["result"]["infrastructure_reservation"] == terms
            and row["actual_input_tokens"] == row["actual_output_tokens"] == 0
            and row["reserved_input_tokens"] == row["reserved_output_tokens"] == 0
            and row["reserved_microdollars"] == seconds * grant.microdollars_per_second
            and set(row["result"])
            == {"artifact", "infrastructure_reservation", "infrastructure_receipt"}
        )
        measured = row["infrastructure_receipt"]
        elapsed = measured["elapsed_milliseconds"]
        _require(
            type(elapsed) is int
            and 0 <= elapsed <= seconds * 1000
            and measured
            == {
                **terms,
                "kind": "measured-infrastructure",
                "elapsed_milliseconds": elapsed,
                "cost_microdollars": (elapsed * grant.microdollars_per_second + 999) // 1000,
            }
            and measured["cost_microdollars"] == row["actual_microdollars"]
        )
        ref = row["result"]["artifact"]
        if stage == "preflight":
            probe = Preflight.model_validate(_read(self.output_artifacts, ref))
            _require(
                probe.image == request.image
                and set(probe.checks) == PREFLIGHT_CHECKS
                and all(probe.checks.values())
            )
            return row, ref, None
        command = owned_semantic_commands()[STAGES.index(stage) - 1]
        nonce = validate_execution(
            ExecutionReceipt.model_validate(_read(self.output_artifacts, ref)),
            command=command,
            snapshot_digest=digest_json(files),
            image=request.image,
            operation_id=grant.account_id + ":" + stage,
            nodes=(command.argv[-1],),
            expected_failures=(),
        )
        return row, ref, nonce

    def validate_completed(
        self,
        request: OwnedSemanticRequest,
        evidence_artifact: str,
    ) -> OwnedSemanticExecution:
        """Reconstruct actual receipts at their ledger times under current data-use policy."""
        try:
            grant, subject, files, binding_ref = self._inputs(request, active=False)
            self._account(grant, binding_ref)
            evidence = OwnedSemanticExecution.model_validate(
                _read(self.output_artifacts, evidence_artifact)
            )
            checkpoint = self.ledger.checkpoint_receipt(
                grant.account_id, "owned-semantic-completed-v1"
            )
            _require(checkpoint is not None and checkpoint["artifact_digest"] == evidence_artifact)
            assert checkpoint is not None
            completed = _time(checkpoint["created_at"])
            _require(
                grant.issued_at <= completed < self._deadline(grant) and completed <= self.clock()
            )
            refs = (
                evidence.preflight_artifact,
                evidence.acceptance_artifact,
                evidence.regression_artifact,
            )
            rows = []
            nonces = []
            binding_checkpoint = self.ledger.checkpoint_receipt(
                grant.account_id, "owned-semantic-binding-v1"
            )
            assert binding_checkpoint is not None
            prior_time = _time(binding_checkpoint["created_at"])
            for stage, ref in zip(STAGES, refs, strict=True):
                row, actual_ref, nonce = self._operation(request, grant, files, binding_ref, stage)
                _require(
                    actual_ref == ref
                    and prior_time
                    <= _time(row["created_at"])
                    <= _time(row["settled_at"])
                    <= completed
                )
                prior_time = _time(row["settled_at"])
                rows.append(row)
                if nonce is not None:
                    nonces.append(nonce)
            account = self.ledger.account(grant.account_id)
            _require(
                len(set(nonces)) == 2
                and account["reserved_microdollars"] == 0
                and evidence.account_id == grant.account_id
                and evidence.request_digest == grant.request_digest
                and evidence.authorization_digest == digest_json(grant.model_dump(mode="json"))
                and evidence.subject_artifact == request.subject_artifact
                and evidence.binding_artifact == binding_ref
                and evidence.candidate_digest
                == digest_json(
                    {
                        subject.module_path: subject.candidate_source,
                        subject.regression_path: subject.regression_source,
                    }
                )
                and evidence.executed_snapshot_digest == digest_json(files)
                and evidence.operation_receipt_digests
                == tuple(row["receipt_digest"] for row in rows)
                and evidence.infrastructure_microdollars
                == sum(row["actual_microdollars"] for row in rows)
                == account["spent_microdollars"]
            )
            current, _, _, current_binding = self._inputs(request, active=False)
            _require(current == grant and current_binding == binding_ref)
            return evidence
        except Exception:
            raise SemanticPreparationFailure(
                "Owned semantic completed evidence is unavailable or invalid"
            ) from None

    async def run(self, request: OwnedSemanticRequest) -> str:
        """Run exactly preflight/acceptance/regression or consume exact completed evidence."""
        try:
            grant, subject, files, binding_ref = self._inputs(request, active=True)
            self.ledger.require_program_enrollment()
            self.ledger.create_account(
                grant.account_id,
                _budget(grant),
                infrastructure_microdollars=grant.infrastructure_microdollars,
                total_microdollars=grant.infrastructure_microdollars,
            )
            written = _put(
                self.output_artifacts, self._binding_document(request, grant, subject, files)
            )
            _require(written == binding_ref)
            self.ledger.checkpoint(grant.account_id, "owned-semantic-binding-v1", binding_ref)
            self._account(grant, binding_ref)
            previous = self.ledger.checkpoint_receipt(
                grant.account_id, "owned-semantic-completed-v1"
            )
            if previous is not None:
                self.validate_completed(request, previous["artifact_digest"])
                return str(previous["artifact_digest"])
            runner = DockerRunner(request.image)
            refs = []
            receipts = []

            def guard() -> None:
                current, _, _, current_binding = self._inputs(request, active=True)
                _require(current == grant and current_binding == binding_ref)
                self._account(grant, binding_ref)

            for stage in STAGES:
                guard()
                seconds = 255 if stage == "preflight" else grant.command_seconds + OVERHEAD_SECONDS
                operation_id = grant.account_id + ":" + stage
                cached = self.ledger.reserve_infrastructure(
                    grant.account_id,
                    operation_id,
                    max_seconds=seconds,
                    microdollars_per_second=grant.microdollars_per_second,
                    rate_card_version=grant.rate_card_version,
                    binding_digest=digest_json({"binding": binding_ref, "stage": stage}),
                )
                if cached is None:

                    async def work(
                        stage: str = stage, operation_id: str = operation_id
                    ) -> dict[str, Any]:
                        if stage == "preflight":
                            return {
                                "artifact": _put(self.output_artifacts, await runner.preflight())
                            }
                        command = owned_semantic_commands()[STAGES.index(stage) - 1]
                        summary = await verify(
                            files,
                            (command,),
                            runner,
                            self.output_artifacts,
                            timeout=grant.command_seconds,
                            workflow_id=operation_id,
                        )
                        return {"artifact": summary["commands"][0]["artifact_digest"]}

                    started = time.monotonic_ns()
                    result = await _guarded(work(), guard)
                    elapsed = (time.monotonic_ns() - started + 999_999) // 1_000_000
                    self.ledger.settle_infrastructure(
                        operation_id, elapsed_milliseconds=elapsed, result=result
                    )
                guard()
                row, ref, _ = self._operation(request, grant, files, binding_ref, stage)
                refs.append(ref)
                receipts.append(row)
            guard()
            evidence = OwnedSemanticExecution(
                account_id=grant.account_id,
                request_digest=grant.request_digest,
                authorization_digest=digest_json(grant.model_dump(mode="json")),
                binding_artifact=binding_ref,
                subject_artifact=request.subject_artifact,
                candidate_digest=digest_json(
                    {
                        subject.module_path: subject.candidate_source,
                        subject.regression_path: subject.regression_source,
                    }
                ),
                executed_snapshot_digest=digest_json(files),
                preflight_artifact=refs[0],
                acceptance_artifact=refs[1],
                regression_artifact=refs[2],
                operation_receipt_digests=tuple(row["receipt_digest"] for row in receipts),
                infrastructure_microdollars=sum(row["actual_microdollars"] for row in receipts),
            )
            artifact = _put(self.output_artifacts, evidence)
            self.ledger.checkpoint(grant.account_id, "owned-semantic-completed-v1", artifact)
            self.validate_completed(request, artifact)
            return artifact
        except Exception:
            raise SemanticPreparationFailure(
                "Owned semantic preparation stopped; inspect protected accounting"
            ) from None
