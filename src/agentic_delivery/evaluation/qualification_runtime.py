"""Metered deterministic qualification checks; never admits a historical task.

The controller and its authorization callbacks are trusted. Source, oracle, reference,
receipts and failure details remain in evaluator-only stores, outside worker scopes.
"""

import asyncio
import copy
import json
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from agentic_delivery.agents.evidence import ExecutionReceipt, Preflight
from agentic_delivery.config import Budget, CommandProfile, Settings
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    PreparationRequest,
    PreparedQualification,
    _files,
    _read,
    _scopes,
    parse_provenance,
    parse_task,
    parse_usage_authorization,
    prepare_qualification,
)
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import safe_path
from agentic_delivery.execution.verification import report_verdict, verify
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

POLL_SECONDS = 1.0
OVERHEAD_SECONDS = 240
PREFLIGHT_CHECKS = {
    "nonroot",
    "no_socket",
    "readonly_root",
    "egress_denied",
    "no_new_privileges",
    "capabilities_dropped",
    "workspace_bounded",
}


class RuntimeFailure(ValueError):
    """Sanitized controller failure; no failed/uncertain execution becomes admission."""


class DeterministicRequest(Contract):
    schema_version: Literal[1] = 1
    preparation: PreparationRequest
    behavior_nodes: tuple[NonEmpty, ...] = Field(min_length=1, max_length=1000)
    regression_nodes: tuple[NonEmpty, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def nodes(self) -> "DeterministicRequest":
        both = self.behavior_nodes + self.regression_nodes
        if len(set(both)) != len(both):
            raise ValueError("Duplicate or overlapping qualification nodes")
        for node in both:
            if len(node) > 2048 or "::" not in node:
                raise ValueError("Qualification requires bounded explicit pytest node identities")
            safe_path(node.split("::", 1)[0])
        return self


class RuntimeAuthorization(Contract):
    """Explicit trusted controller grant, separate from data rights and model permission."""

    schema_version: Literal[1] = 1
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    request_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    budget: Budget
    infrastructure_microdollars: int = Field(gt=0, strict=True, le=2**63 - 1)
    total_microdollars: int = Field(gt=0, strict=True, le=2**63 - 1)
    microdollars_per_second: int = Field(gt=0, strict=True, le=10**9)
    rate_card_version: NonEmpty = Field(max_length=200)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class RuntimeExecution(Contract):
    variant: Literal["baseline", "reference"]
    suite: Literal["acceptance", "regression"]
    repetition: int = Field(ge=1, le=3, strict=True)
    operation_id: NonEmpty
    receipt_artifact: Digest
    infrastructure_receipt_digest: Digest


class DeterministicEvidence(Contract):
    schema_version: Literal[1] = 1
    status: Literal["DETERMINISTIC_CHECKS_PASSED_NOT_QUALIFIED"] = (
        "DETERMINISTIC_CHECKS_PASSED_NOT_QUALIFIED"
    )
    admitted: Literal[False] = False
    account_id: NonEmpty
    request_digest: Digest
    prepared_artifact: Digest
    authorization_digest: Digest
    preflight_artifact: Digest
    preflight_operation_id: NonEmpty
    executions: tuple[RuntimeExecution, ...] = Field(min_length=12, max_length=12)


def _require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeFailure(message)


def _put(store: ArtifactStore, value: Any) -> str:
    return store.put(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def _prepared_binding(prepared: PreparedQualification) -> dict[str, Any]:
    return prepared.model_dump(mode="json", exclude={"prepared_at"})


def _ledger_scope(settings: Settings, ledger: EvaluationExecutionStore, worker_root: Path) -> None:
    if ledger.sqlite:
        database = Path(str(ledger.engine.url.database)).resolve()
        _require(
            not database.is_relative_to(worker_root.resolve())
            and not any(
                repository.local_repository is not None
                and database.is_relative_to(repository.local_repository.resolve())
                for repository in settings.repositories
            ),
            "Evaluation ledger is exposed to a worker repository",
        )


def validate_execution(
    receipt: ExecutionReceipt,
    *,
    command: CommandProfile,
    snapshot_digest: str,
    image: str,
    operation_id: str,
    nodes: tuple[str, ...],
    expected_failures: tuple[str, ...],
) -> str:
    """Allow only the frozen baseline call failures, never setup/collection/infra errors."""
    binding = receipt.verification_binding
    _require(
        set(binding) == {"nonce", "snapshot_digest", "command_digest", "argv"}
        and isinstance(binding.get("nonce"), str)
        and re.fullmatch(r"[0-9a-f]{32}", binding["nonce"]) is not None
        and binding["snapshot_digest"] == receipt.snapshot_digest == snapshot_digest
        and binding["command_digest"] == digest_json(command.model_dump(mode="json"))
        and binding["argv"] == list(command.argv)
        and receipt.command_id == command.id
        and receipt.argv == command.argv
        and receipt.image == image
        and receipt.workflow_id == operation_id
        and receipt.timed_out is False
        and receipt.report_error is None,
        "Execution does not bind the authorized completed operation",
    )
    report = copy.deepcopy(receipt.verification_report)
    _require(isinstance(report, dict), "Missing structured verification report")
    assert report is not None
    failed: set[str] = set()
    for phase in report.get("phases", []):
        if (
            isinstance(phase, dict)
            and phase.get("when") == "call"
            and phase.get("outcome") == "failed"
            and phase.get("wasxfail") is False
        ):
            failed.add(phase["nodeid"])
            phase["outcome"] = "passed"
    expected_exit = 1 if failed else 0
    _require(
        type(report.get("exit_code")) is int
        and receipt.exit_code == report.get("exit_code") == expected_exit,
        "Execution failure is not a completed pytest test failure",
    )
    report["exit_code"] = 0
    passed, _, _ = report_verdict(
        report, binding, expected_tests=command.expected_tests, exit_code=0
    )
    _require(passed, "Incomplete or unsupported collector evidence")
    _require(set(report["collected"]) == set(nodes), "Collection differs from frozen nodes")
    _require(failed == set(expected_failures), "Unexpected baseline/reference test outcome")
    return str(binding["nonce"])


def validate_deterministic_evidence(
    request: DeterministicRequest,
    evidence_artifact: str,
    *,
    authorization: RuntimeAuthorization,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    now: datetime,
) -> DeterministicEvidence:
    """Read-only validation of the complete trusted checkpoint, never task admission."""
    try:
        _ledger_scope(settings, ledger, worker_root)
        prepared = prepare_qualification(
            request.preparation,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_root=output_artifacts.root,
            worker_root=worker_root,
            now=now,
        )
        task = parse_task(_read(protected_artifacts, request.preparation.task_artifact))
        grant = RuntimeAuthorization.model_validate(authorization.model_dump(mode="json"))
        evidence = DeterministicEvidence.model_validate(_read(output_artifacts, evidence_artifact))
        authorization_digest = digest_json(grant.model_dump(mode="json"))
        _require(
            grant.issued_at
            <= now
            < min(grant.expires_at, grant.issued_at + timedelta(seconds=task.budget.wall_seconds))
            and grant.request_digest
            == evidence.request_digest
            == digest_json(request.model_dump(mode="json"))
            and grant.execution_config_digest == prepared.execution_config_digest
            and grant.preparation_policy_digest == prepared.preparation_policy_digest
            and grant.budget == task.budget
            and evidence.authorization_digest == authorization_digest
            and evidence.account_id == grant.account_id
            and _read(output_artifacts, evidence.prepared_artifact) == _prepared_binding(prepared),
            "Deterministic evidence has stale or mismatched authority/inputs",
        )
        binding = {
            "request": request.model_dump(mode="json"),
            "authorization_digest": authorization_digest,
        }
        for stage, expected in (
            ("deterministic-binding-v1", None),
            ("deterministic-complete-v1", evidence_artifact),
        ):
            checkpoint = ledger.checkpoint_receipt(grant.account_id, stage)
            _require(checkpoint is not None, "Missing trusted deterministic checkpoint")
            assert checkpoint is not None
            _require(
                checkpoint["artifact_digest"] == expected
                if expected
                else _read(output_artifacts, checkpoint["artifact_digest"]) == binding,
                "Deterministic checkpoint differs from evidence",
            )

        def operation(stage: str, artifact: str, result_key: str, seconds: int) -> dict[str, Any]:
            row = ledger.operation_receipt(grant.account_id, grant.account_id + ":" + stage)
            terms = {
                "schema_version": 1,
                "kind": "infrastructure",
                "max_seconds": seconds,
                "microdollars_per_second": grant.microdollars_per_second,
                "rate_card_version": grant.rate_card_version,
                "binding_digest": digest_json(
                    {**binding, "prepared": evidence.prepared_artifact, "stage": stage}
                ),
            }
            _require(
                row["status"] == "SETTLED"
                and row.get("operation_kind") == "infrastructure"
                and row["result"][result_key] == artifact
                and row["result"]["infrastructure_reservation"] == terms
                and row["actual_input_tokens"] == row["actual_output_tokens"] == 0,
                "Deterministic operation lacks matching settled infrastructure evidence",
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
                and measured["cost_microdollars"] == row["actual_microdollars"],
                "Infrastructure duration/accounting mismatch",
            )
            return row

        _require(
            evidence.preflight_operation_id == grant.account_id + ":preflight",
            "Preflight identity mismatch",
        )
        operation("preflight", evidence.preflight_artifact, "preflight_artifact", 255)
        probe = Preflight.model_validate(_read(output_artifacts, evidence.preflight_artifact))
        _require(
            probe.image == task.image
            and set(probe.checks) == PREFLIGHT_CHECKS
            and all(probe.checks.values()),
            "Incomplete preflight",
        )
        expected_matrix = {
            (v, s, r)
            for v in ("baseline", "reference")
            for s in ("acceptance", "regression")
            for r in (1, 2, 3)
        }
        _require(
            {(x.variant, x.suite, x.repetition) for x in evidence.executions} == expected_matrix,
            "Incomplete deterministic matrix",
        )
        nonces: set[str] = set()
        for entry in evidence.executions:
            stage = f"{entry.variant}-{entry.suite}-{entry.repetition}"
            row = operation(
                stage,
                entry.receipt_artifact,
                "execution_artifact",
                task.budget.command_seconds + OVERHEAD_SECONDS,
            )
            _require(
                row["receipt_digest"] == entry.infrastructure_receipt_digest
                and row["operation_id"] == entry.operation_id,
                "Infrastructure receipt reference mismatch",
            )
            nonce = validate_execution(
                ExecutionReceipt.model_validate(_read(output_artifacts, entry.receipt_artifact)),
                command=task.acceptance_commands[0]
                if entry.suite == "acceptance"
                else task.regression_commands[0],
                snapshot_digest=prepared.baseline_snapshot_digest
                if entry.variant == "baseline"
                else prepared.reference_snapshot_digest,
                image=task.image,
                operation_id=entry.operation_id,
                nodes=request.behavior_nodes
                if entry.suite == "acceptance"
                else request.regression_nodes,
                expected_failures=request.behavior_nodes
                if entry.variant == "baseline" and entry.suite == "acceptance"
                else (),
            )
            _require(nonce not in nonces, "Duplicate deterministic nonce")
            nonces.add(nonce)
        return evidence
    except Exception:
        raise RuntimeFailure("Deterministic evidence validation failed") from None


def validate_completed_deterministic_evidence(
    request: DeterministicRequest,
    evidence_artifact: str,
    *,
    authorization: RuntimeAuthorization,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    now: datetime,
) -> DeterministicEvidence:
    """Validate historical execution at its recorded completion, plus current data rights.

    The caller supplies the trusted current clock and original grant. Historical time
    comes only from the immutable ledger checkpoint, never a caller-selected past time.
    This performs no execution, writes, grant renewal or historical-task admission.
    """
    try:
        request = DeterministicRequest.model_validate(request.model_dump(mode="json"))
        grant = RuntimeAuthorization.model_validate(authorization.model_dump(mode="json"))
        _require(now.tzinfo is not None and now.utcoffset() is not None, "Aware clock required")
        _ledger_scope(settings, ledger, worker_root)
        current = prepare_qualification(
            request.preparation,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_root=output_artifacts.root,
            worker_root=worker_root,
            now=now,
        )

        def timestamp(value: Any) -> datetime:
            _require(isinstance(value, str), "Missing ledger timestamp")
            result = datetime.fromisoformat(value)
            _require(
                result.tzinfo is not None and result.utcoffset() is not None,
                "Naive ledger timestamp",
            )
            return result

        complete = ledger.checkpoint_receipt(grant.account_id, "deterministic-complete-v1")
        bound = ledger.checkpoint_receipt(grant.account_id, "deterministic-binding-v1")
        _require(complete is not None and bound is not None, "Missing trusted checkpoint")
        assert complete is not None and bound is not None
        _require(
            complete["artifact_digest"] == evidence_artifact
            and complete["account_id"] == bound["account_id"] == grant.account_id
            and complete["stage"] == "deterministic-complete-v1"
            and bound["stage"] == "deterministic-binding-v1",
            "Checkpoint identity differs from requested evidence",
        )
        completed_at = timestamp(complete["created_at"])
        previous = timestamp(bound["created_at"])
        deadline = min(
            grant.expires_at, grant.issued_at + timedelta(seconds=grant.budget.wall_seconds)
        )
        _require(
            grant.issued_at <= previous <= completed_at < deadline and completed_at <= now,
            "Completion is future-dated or outside original execution authority",
        )
        stages = ["preflight"] + [
            f"{variant}-{suite}-{repetition}"
            for variant in ("baseline", "reference")
            for suite in ("acceptance", "regression")
            for repetition in (1, 2, 3)
        ]
        for stage in stages:
            operation_id = grant.account_id + ":" + stage
            row = ledger.operation_receipt(grant.account_id, operation_id)
            _require(
                row["account_id"] == grant.account_id
                and row["operation_id"] == operation_id
                and row["status"] == "SETTLED",
                "Historical operation is uncertain or has wrong identity",
            )
            created_at, settled_at = timestamp(row["created_at"]), timestamp(row["settled_at"])
            _require(
                previous <= created_at <= settled_at <= completed_at,
                "Operation timestamps are outside the ordered completed execution",
            )
            previous = settled_at
        evidence = validate_deterministic_evidence(
            request,
            evidence_artifact,
            authorization=grant,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            now=completed_at,
        )
        _require(
            _read(output_artifacts, evidence.prepared_artifact) == _prepared_binding(current),
            "Current preparation differs from completed evidence",
        )
        return evidence
    except Exception:
        raise RuntimeFailure("Completed deterministic evidence validation failed") from None


async def _guarded(work: Awaitable[Any], guard: Callable[[], None]) -> Any:
    task = asyncio.ensure_future(work)
    try:
        while not task.done():
            guard()
            await asyncio.wait({task}, timeout=POLL_SECONDS)
        return await task
    except BaseException:
        if not task.done():
            task.cancel()
        # Keep ownership of cleanup even if the parent receives another cancellation.
        while not task.done():
            with suppress(asyncio.CancelledError):
                await asyncio.shield(task)
        with suppress(asyncio.CancelledError):
            task.result()
        # A cleanup failure supersedes the requested cancellation/revocation.
        raise


async def run_deterministic_qualification(
    request: DeterministicRequest,
    *,
    settings_provider: Callable[[], Settings],
    policy_provider: Callable[[], PreparationPolicy],
    authorization_provider: Callable[[], RuntimeAuthorization],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Run preflight plus 3 x (base/reference x acceptance/regression), with resume.

    Returns only metadata. No model, admission, campaign or worker export is invoked.
    Unknown operations keep their reservations and are never automatically reissued.
    """
    try:
        return await _run(
            request,
            settings_provider=settings_provider,
            policy_provider=policy_provider,
            authorization_provider=authorization_provider,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            clock=clock,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise RuntimeFailure(
            "Deterministic qualification stopped; inspect protected evidence"
        ) from None


async def _run(
    request: DeterministicRequest,
    *,
    settings_provider: Callable[[], Settings],
    policy_provider: Callable[[], PreparationPolicy],
    authorization_provider: Callable[[], RuntimeAuthorization],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    request = DeterministicRequest.model_validate(request.model_dump(mode="json"))
    grant = RuntimeAuthorization.model_validate(authorization_provider().model_dump(mode="json"))
    settings = settings_provider()
    policy = policy_provider()
    prepared = prepare_qualification(
        request.preparation,
        settings=settings,
        policy=policy,
        protected_artifacts=protected_artifacts,
        output_root=output_artifacts.root,
        worker_root=worker_root,
        now=clock(),
    )
    task = parse_task(_read(protected_artifacts, request.preparation.task_artifact))
    provenance = parse_provenance(
        _read(protected_artifacts, request.preparation.provenance_artifact)
    )
    rights = parse_usage_authorization(
        _read(protected_artifacts, provenance.usage_authorization_artifact)
    )
    _require(
        grant.request_digest == digest_json(request.model_dump(mode="json"))
        and grant.execution_config_digest == prepared.execution_config_digest
        and grant.preparation_policy_digest == prepared.preparation_policy_digest
        and grant.budget == task.budget,
        "Execution authorization differs from prepared inputs",
    )
    # Reserve with real infrastructure terms; the model token budget is never fabricated.
    maximum_seconds = 255 + 12 * (task.budget.command_seconds + OVERHEAD_SECONDS)
    _require(
        maximum_seconds * grant.microdollars_per_second
        <= min(grant.infrastructure_microdollars, grant.total_microdollars),
        "Infrastructure ceiling cannot cover the declared bounded batch",
    )
    _ledger_scope(settings, ledger, worker_root)
    authorization_digest = digest_json(grant.model_dump(mode="json"))
    deadline = min(grant.expires_at, grant.issued_at + timedelta(seconds=task.budget.wall_seconds))

    def guard() -> None:
        current = clock()
        _require(
            current.tzinfo is not None
            and grant.issued_at <= current < deadline
            and rights.issued_at <= current < rights.expires_at,
            "Execution/data authorization expired or is not yet valid",
        )
        live = settings_provider()
        _require(
            live.admissions_enabled
            and live.repository(task.item.repository).model_data_authorized
            and live.execution_digest(task.item.repository) == grant.execution_config_digest
            and digest_json(policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
            and digest_json(authorization_provider().model_dump(mode="json"))
            == authorization_digest,
            "Current controller authority or configuration changed",
        )
        _scopes(protected_artifacts.root, output_artifacts.root, worker_root)
        for repository in live.repositories:
            if repository.local_repository is not None:
                _scopes(
                    protected_artifacts.root, output_artifacts.root, repository.local_repository
                )
        _ledger_scope(live, ledger, worker_root)

    guard()
    ledger.create_account(
        grant.account_id,
        grant.budget,
        infrastructure_microdollars=grant.infrastructure_microdollars,
        total_microdollars=grant.total_microdollars,
    )
    # This account may be reused only for the exact request and grant, including its deadline.
    binding = {
        "request": request.model_dump(mode="json"),
        "authorization_digest": authorization_digest,
    }
    ledger.checkpoint(grant.account_id, "deterministic-binding-v1", _put(output_artifacts, binding))
    prepared_ref = _put(output_artifacts, _prepared_binding(prepared))
    source = _files(protected_artifacts, task.snapshot_artifact)
    oracle = _files(protected_artifacts, task.oracle_artifact)
    baseline = {**source, **oracle}
    assert task.reference_snapshot_artifact is not None
    reference = _files(protected_artifacts, task.reference_snapshot_artifact)
    runner = DockerRunner(task.image)

    async def operation(
        stage: str, seconds: int, work: Callable[[str], Awaitable[dict[str, Any]]]
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        guard()
        operation_id = grant.account_id + ":" + stage
        operation_binding = digest_json({**binding, "prepared": prepared_ref, "stage": stage})
        cached = ledger.reserve_infrastructure(
            grant.account_id,
            operation_id,
            max_seconds=seconds,
            microdollars_per_second=grant.microdollars_per_second,
            rate_card_version=grant.rate_card_version,
            binding_digest=operation_binding,
        )
        if cached is None:
            started = time.monotonic_ns()
            value = await _guarded(work(operation_id), guard)
            elapsed_ms = (time.monotonic_ns() - started + 999_999) // 1_000_000
            # The measured await includes Docker cleanup. Errors/cancellation do not settle.
            ledger.settle_infrastructure(
                operation_id, elapsed_milliseconds=elapsed_ms, result=value
            )
        receipt = ledger.operation_receipt(grant.account_id, operation_id)
        guard()
        _require(receipt["status"] == "SETTLED", "Uncertain infrastructure operation")
        return operation_id, receipt["result"], receipt

    async def preflight(_: str) -> dict[str, Any]:
        return {"preflight_artifact": _put(output_artifacts, await runner.preflight())}

    preflight_id, observed, _ = await operation("preflight", 255, preflight)
    preflight_ref = observed["preflight_artifact"]
    probe = Preflight.model_validate(_read(output_artifacts, preflight_ref))
    _require(
        probe.image == task.image
        and set(probe.checks) == PREFLIGHT_CHECKS
        and all(probe.checks.values()),
        "Isolation preflight failed",
    )
    executions: list[RuntimeExecution] = []
    nonces: set[str] = set()
    for variant, files in (("baseline", baseline), ("reference", reference)):
        for suite, command, nodes in (
            ("acceptance", task.acceptance_commands[0], request.behavior_nodes),
            ("regression", task.regression_commands[0], request.regression_nodes),
        ):
            for repetition in (1, 2, 3):
                # Revalidate all protected inputs at each new external effect boundary.
                fresh = prepare_qualification(
                    request.preparation,
                    settings=settings_provider(),
                    policy=policy_provider(),
                    protected_artifacts=protected_artifacts,
                    output_root=output_artifacts.root,
                    worker_root=worker_root,
                    now=clock(),
                )
                _require(
                    _prepared_binding(fresh) == _prepared_binding(prepared),
                    "Prepared evidence changed",
                )

                async def execute(
                    operation_id: str,
                    files: dict[str, str] = files,
                    command: CommandProfile = command,
                ) -> dict[str, Any]:
                    summary = await verify(
                        files,
                        (command,),
                        runner,
                        output_artifacts,
                        timeout=task.budget.command_seconds,
                        workflow_id=operation_id,
                    )
                    return {"execution_artifact": summary["commands"][0]["artifact_digest"]}

                operation_id, value, accounting = await operation(
                    f"{variant}-{suite}-{repetition}",
                    task.budget.command_seconds + OVERHEAD_SECONDS,
                    execute,
                )
                execution_ref = value["execution_artifact"]
                receipt = ExecutionReceipt.model_validate(_read(output_artifacts, execution_ref))
                nonce = validate_execution(
                    receipt,
                    command=command,
                    snapshot_digest=digest_json(files),
                    image=task.image,
                    operation_id=operation_id,
                    nodes=nodes,
                    expected_failures=request.behavior_nodes
                    if variant == "baseline" and suite == "acceptance"
                    else (),
                )
                _require(nonce not in nonces, "Repeated collector nonce")
                nonces.add(nonce)
                executions.append(
                    RuntimeExecution.model_validate(
                        {
                            "variant": variant,
                            "suite": suite,
                            "repetition": repetition,
                            "operation_id": operation_id,
                            "receipt_artifact": execution_ref,
                            "infrastructure_receipt_digest": accounting["receipt_digest"],
                        }
                    )
                )
    guard()
    evidence = DeterministicEvidence(
        account_id=grant.account_id,
        request_digest=grant.request_digest,
        prepared_artifact=prepared_ref,
        authorization_digest=authorization_digest,
        preflight_artifact=preflight_ref,
        preflight_operation_id=preflight_id,
        executions=tuple(executions),
    )
    result_ref = _put(output_artifacts, evidence.model_dump(mode="json"))
    ledger.checkpoint(grant.account_id, "deterministic-complete-v1", result_ref)
    return {
        "status": evidence.status,
        "admitted": False,
        "evidence_artifact": result_ref,
        "account_id": grant.account_id,
    }
