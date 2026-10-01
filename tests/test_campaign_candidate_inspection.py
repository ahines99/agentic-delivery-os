"""Owned sealed candidate reads with every effect boundary disabled."""

# ruff: noqa: F401, F811
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update
from test_campaign_candidate import (
    allocation_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    controlled_scoring,
    put,
)

from agentic_delivery.evaluation import campaign_candidate_inspection as inspection
from agentic_delivery.evaluation import execution_store
from agentic_delivery.evaluation.campaign_allocation import ALLOCATION_CHECKPOINT
from agentic_delivery.evaluation.campaign_candidate import RESULT_CHECKPOINT
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


async def completed(c):
    sealed = await c.create().run(c.case.task)
    allocator = c.allocation.create()
    ledger = c.case.ledger
    state = {"now": c.allocated.attempt.deadline + timedelta(seconds=1)}
    use = inspection.CandidateConsumptionAuthorization(
        purpose="campaign-report",
        ledger_identity=c.allocated.ledger_identity,
        campaign_artifact=c.allocated.attempt.campaign_artifact,
        ordinal=c.allocated.attempt.ordinal,
        phase="development",
        allocation_artifact=ledger.checkpoint_receipt(
            c.allocation.account_id, ALLOCATION_CHECKPOINT
        )["artifact_digest"],
        attempt_binding_artifact=c.allocated.attempt_binding_artifact,
        execution_binding_artifact=sealed.execution_binding_artifact,
        sealed_candidate_artifact=ledger.checkpoint_receipt(
            c.allocation.account_id, RESULT_CHECKPOINT
        )["artifact_digest"],
        task_manifest_digest=c.allocated.attempt.task_manifest_digest,
        qualification_artifact=c.case.task.qualification_artifact,
        original_authorization_digest=digest_json(c.state["grant"].model_dump(mode="json")),
        original_execution_policy_digest=digest_json(c.state["policy"].model_dump(mode="json")),
        original_allocation_policy_digest=digest_json(
            c.allocation.state["policy"].model_dump(mode="json")
        ),
        issued_at=state["now"],
        expires_at=state["now"] + timedelta(hours=1),
    )
    state["grant"] = use
    state["policy"] = inspection.CandidateConsumptionPolicy(
        enabled=True,
        ledger_identity=use.ledger_identity,
        approved_authorizations=(digest_json(use.model_dump(mode="json")),),
        allowed_purposes=("campaign-report",),
    )
    kwargs = dict(
        ledger=ledger,
        campaign_artifacts=allocator.campaign_artifacts,
        output_artifacts=c.case.output,
        authority=allocator.authority,
        original_authorization=c.state["grant"],
        original_execution_policy=c.state["policy"],
        original_allocation_policy=c.allocation.state["policy"],
        consumption_authorization_provider=lambda: state["grant"],
        consumption_policy_provider=lambda: state["policy"],
        clock=lambda: state["now"],
    )
    return SimpleNamespace(
        sealed=sealed,
        state=state,
        kwargs=kwargs,
        read=lambda: inspection.validate_sealed_candidate(c.case.task, **kwargs),
    )


def snapshot(ledger):
    with ledger.engine.connect() as conn:
        return {
            table.name: [dict(row) for row in conn.execute(select(table)).mappings()]
            for table in (
                execution_store.accounts,
                execution_store.operations,
                execution_store.checkpoints,
            )
        }


def deny_effects(c, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Reader attempted an effect")

    monkeypatch.delenv(c.config.api_key_env, raising=False)
    monkeypatch.setattr(StructuredModel, "generate", denied)
    monkeypatch.setattr(ArtifactStore, "put", denied)
    for name in (
        "create_account",
        "reserve",
        "reserve_infrastructure",
        "settle",
        "settle_infrastructure",
        "checkpoint",
        "record_observation",
    ):
        monkeypatch.setattr(c.case.ledger, name, denied)
    monkeypatch.setattr("agentic_delivery.execution.docker.DockerRunner.__init__", denied)


@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_expired_execution_is_read_without_credentials_or_effects(
    candidate_case, monkeypatch
):
    c = candidate_case
    if c.arm["arm"] == "B":
        c.state["reject"] = True
    data = await completed(c)
    before = snapshot(c.case.ledger)
    counts = len(c.state["calls"]), len(c.state["docker"])
    deny_effects(c, monkeypatch)
    result = await data.read()
    assert result.sealed == data.sealed and not result.strict_success
    assert before == snapshot(c.case.ledger)
    assert counts == (len(c.state["calls"]), len(c.state["docker"]))
    await c.client.aclose()


@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_normal_failed_candidate_reconstructs_without_success(candidate_case, monkeypatch):
    c = candidate_case
    c.state["validation_failure"] = c.arm["arm"] == "A"
    c.state["always_reject"] = c.arm["arm"] == "B"
    data = await completed(c)
    deny_effects(c, monkeypatch)
    result = await data.read()
    assert result.sealed.status == "FAILED" and result.sealed.candidate_artifact
    counts = result.criterion_execution.counts
    required = len(c.case.task.item.acceptance_criteria)
    assert counts.total == required and counts.unavailable == 0
    if c.arm["arm"] == "A":
        assert counts.not_executed == required and counts.passed == 0
    else:
        assert counts.passed == required and counts.not_executed == 0
    await c.client.aclose()


@pytest.mark.parametrize(
    "field",
    [
        "purpose",
        "ledger_identity",
        "campaign_artifact",
        "ordinal",
        "phase",
        "allocation_artifact",
        "attempt_binding_artifact",
        "execution_binding_artifact",
        "sealed_candidate_artifact",
        "task_manifest_digest",
        "qualification_artifact",
        "original_authorization_digest",
        "original_execution_policy_digest",
        "original_allocation_policy_digest",
        "expires_at",
    ],
)
async def test_exact_current_consumption_grant_required(candidate_case, monkeypatch, field):
    c = candidate_case
    data = await completed(c)
    value = {
        "purpose": "scoring",
        "ordinal": 9999,
        "phase": "test",
        "expires_at": data.state["now"],
    }.get(field, "f" * 64)
    data.state["grant"] = data.state["grant"].model_copy(update={field: value})
    # Even explicitly reapproved altered refs cannot replace the historical chain.
    data.state["policy"] = data.state["policy"].model_copy(
        update={
            "approved_authorizations": (digest_json(data.state["grant"].model_dump(mode="json")),)
        }
    )
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    await c.client.aclose()


@pytest.mark.parametrize("mutation", ["missing", "unknown", "chronology", "extra"])
async def test_ledger_chain_mutations_refused(candidate_case, monkeypatch, mutation):
    c = candidate_case
    data = await completed(c)
    identity = c.allocation.account_id + ":candidate:build:0"
    with c.case.ledger.engine.begin() as conn:
        if mutation == "missing":
            conn.execute(
                delete(execution_store.operations).where(
                    execution_store.operations.c.id == identity
                )
            )
        elif mutation == "extra":
            row = dict(
                conn.execute(
                    select(execution_store.operations).where(
                        execution_store.operations.c.id == identity
                    )
                )
                .mappings()
                .one()
            )
            row["id"] += ":extra"
            conn.execute(execution_store.operations.insert().values(**row))
        else:
            conn.execute(
                update(execution_store.operations)
                .where(execution_store.operations.c.id == identity)
                .values(
                    **(
                        {"status": "RESERVED"}
                        if mutation == "unknown"
                        else {"created_at": "2099-01-01T00:00:00+00:00"}
                    )
                )
            )
    before = snapshot(c.case.ledger)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    assert before == snapshot(c.case.ledger)
    await c.client.aclose()


@pytest.mark.parametrize("mutation", ["policy", "qualification", "settings", "mid-read"])
async def test_current_authority_remains_required(candidate_case, monkeypatch, mutation):
    c = candidate_case
    data = await completed(c)
    if mutation == "policy":
        data.state["policy"] = data.state["policy"].model_copy(update={"enabled": False})
    elif mutation == "settings":
        c.case.state["settings"] = c.case.state["settings"].model_copy(
            update={"admissions_enabled": False}
        )
    else:
        original = HistoricalTask.validate_qualification
        calls = 0

        def qualification(*args, **kwargs):
            nonlocal calls
            calls += 1
            if mutation == "qualification" or calls >= 4:
                raise ValueError("Owned revoked current use")
            return original(*args, **kwargs)

        monkeypatch.setattr(HistoricalTask, "validate_qualification", qualification)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    await c.client.aclose()


def rebind_result(c, data, sealed):
    reference = put(c.case.output, sealed)
    with c.case.ledger.engine.begin() as conn:
        conn.execute(
            update(execution_store.checkpoints)
            .where(
                execution_store.checkpoints.c.account_id == c.allocation.account_id,
                execution_store.checkpoints.c.stage == RESULT_CHECKPOINT,
            )
            .values(artifact_digest=reference)
        )
    data.state["grant"] = data.state["grant"].model_copy(
        update={"sealed_candidate_artifact": reference}
    )
    data.state["policy"] = data.state["policy"].model_copy(
        update={
            "approved_authorizations": (digest_json(data.state["grant"].model_dump(mode="json")),)
        }
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "infra-reserve",
        "input-price",
        "output-price",
        "rate-card",
        "nonce",
        "context",
        "engine",
        "candidate",
        "reordered",
        "checkpoint-time",
    ],
)
async def test_rehashed_internal_evidence_still_requires_exact_reconstruction(
    candidate_case, monkeypatch, mutation
):
    c = candidate_case
    data = await completed(c)
    sealed = data.sealed.model_dump(mode="json")
    inventory = json.loads(c.case.output.get(sealed["operations_artifact"]))
    if mutation in {"engine", "candidate"}:
        key = "engine_evidence_artifact" if mutation == "engine" else "candidate_artifact"
        value = json.loads(c.case.output.get(sealed[key]))
        value["unbound"] = "owned changed evidence"
        sealed[key] = put(c.case.output, value)
        if mutation == "candidate":
            sealed["candidate_digest"] = digest_json(value)
    elif mutation == "reordered":
        inventory[0], inventory[1] = inventory[1], inventory[0]
    elif mutation == "checkpoint-time":
        with c.case.ledger.engine.begin() as conn:
            conn.execute(
                update(execution_store.checkpoints)
                .where(
                    execution_store.checkpoints.c.account_id == c.allocation.account_id,
                    execution_store.checkpoints.c.stage == RESULT_CHECKPOINT,
                )
                .values(created_at="2099-01-01T00:00:00+00:00")
            )
    else:
        stage = (
            "preflight"
            if mutation == "infra-reserve"
            else "verify:0"
            if mutation == "nonce"
            else "build:0"
        )
        entry = next(entry for entry in inventory if entry["stage"] == stage)
        row = c.case.ledger.operation_receipt(c.allocation.account_id, entry["operation_id"])
        stored = row["result"]
        updates = {}
        if mutation == "infra-reserve":
            updates["reserved_microdollars"] = row["reserved_microdollars"] + 1
        elif mutation == "nonce":
            summary = stored["candidate_result"]
            receipt = json.loads(c.case.output.get(summary["commands"][0]["artifact_digest"]))
            receipt["verification_binding"].pop("nonce")
            receipt["verification_report"]["binding"].pop("nonce")
            summary["commands"][0]["artifact_digest"] = put(c.case.output, receipt)
            updates["result"] = stored
        elif mutation == "context":
            payload = json.loads(c.case.output.get(entry["input_artifact"]))
            payload["context"]["files"]["app.py"] = "VALUE = 999\n"
            entry["input_artifact"] = put(c.case.output, payload)
            with c.case.ledger.engine.begin() as conn:
                conn.execute(
                    update(execution_store.checkpoints)
                    .where(
                        execution_store.checkpoints.c.account_id == c.allocation.account_id,
                        execution_store.checkpoints.c.stage == "candidate-input:build:0",
                    )
                    .values(artifact_digest=entry["input_artifact"])
                )
        else:
            field = {
                "input-price": "input_microdollars_per_million",
                "output-price": "output_microdollars_per_million",
                "rate-card": "rate_card_version",
            }[mutation]
            stored["operation_receipt"][field] = "altered-card" if mutation == "rate-card" else 2
            if mutation == "rate-card":
                stored["rate_card_version"] = "altered-card"
            updates["result"] = stored
        if updates:
            with c.case.ledger.engine.begin() as conn:
                conn.execute(
                    update(execution_store.operations)
                    .where(execution_store.operations.c.id == entry["operation_id"])
                    .values(**updates)
                )
        entry["receipt_digest"] = c.case.ledger.operation_receipt(
            c.allocation.account_id, entry["operation_id"]
        )["receipt_digest"]
    sealed["operations_artifact"] = put(c.case.output, inventory)
    rebind_result(c, data, sealed)
    before = snapshot(c.case.ledger)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    assert before == snapshot(c.case.ledger)
    await c.client.aclose()


@pytest.mark.parametrize(
    "original",
    ["original_authorization", "original_execution_policy", "original_allocation_policy"],
)
async def test_original_proof_cannot_be_rewritten(candidate_case, monkeypatch, original):
    c = candidate_case
    data = await completed(c)
    value = data.kwargs[original]
    field, altered = (
        ("expires_at", value.expires_at + timedelta(hours=1))
        if original == "original_authorization"
        else ("enabled", False)
    )
    data.kwargs[original] = value.model_copy(update={field: altered})
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    await c.client.aclose()


async def test_later_settled_shared_account_stage_does_not_rewrite_candidate(
    candidate_case, monkeypatch
):
    c = candidate_case
    data = await completed(c)
    operation = c.allocation.account_id + ":owned-later-stage"
    c.case.ledger.reserve(c.allocation.account_id, operation, 1, 1, 1)
    c.case.ledger.settle(operation, cost=1, input_tokens=1, output_tokens=1, result={"owned": True})
    before = snapshot(c.case.ledger)
    deny_effects(c, monkeypatch)
    result = await data.read()
    assert operation not in result.operation_ids
    assert before == snapshot(c.case.ledger)
    await c.client.aclose()


async def test_duplicate_ledger_target_is_not_authorized(candidate_case, monkeypatch, tmp_path):
    c = candidate_case
    data = await completed(c)
    other = execution_store.EvaluationExecutionStore(
        "sqlite:///" + (tmp_path / "delivery_eval_other.db").as_posix()
    )
    data.kwargs["ledger"] = other
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.CandidateInspectionFailure):
        await data.read()
    other.engine.dispose()
    await c.client.aclose()


async def test_execution_grant_can_begin_at_original_account_start(candidate_case, monkeypatch):
    c = candidate_case
    c.state["grant"] = c.state["grant"].model_copy(
        update={"issued_at": c.allocated.attempt.started_at}
    )
    data = await completed(c)
    deny_effects(c, monkeypatch)
    assert (await data.read()).sealed == data.sealed
    await c.client.aclose()
