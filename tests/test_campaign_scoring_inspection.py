"""Owned completed scoring inspection; real ledger, controlled authority and collector."""

# ruff: noqa: F401, F811
import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update
from test_campaign_scoring import campaign_scoring, campaign_seed, controlled_scoring, put

from agentic_delivery.evaluation import campaign_scoring_inspection as inspection
from agentic_delivery.evaluation import execution_store, harness
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.campaign_scoring import (
    SCORING_CHECKPOINT,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.scoring_execution import STAGES, ScoringFailure
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


async def completed(c):
    await harness.score_campaign_candidate(
        c.task, c.candidate, c.protected, c.output, authority=c.authority, execution=c.create()
    )
    document = validate_completed_scoring(
        c.task, c.candidate, authority=c.authority, execution=c.create(), output_artifacts=c.output
    )
    state = {"now": c.attempt.deadline + timedelta(seconds=1)}
    grant = c.state["grant"]
    use = inspection.ScoringConsumptionAuthorization(
        purpose="campaign-report",
        ledger_identity=ledger_target_identity(c.ledger),
        account_id=c.attempt.account_id,
        campaign_artifact=grant.campaign_artifact,
        ordinal=grant.ordinal,
        phase=grant.phase,
        attempt_binding_artifact=grant.attempt_binding_artifact,
        scoring_binding_artifact=document["scoring_binding_artifact"],
        candidate_artifact=put(c.output, c.candidate),
        candidate_digest=grant.candidate_digest,
        task_manifest_digest=grant.task_manifest_digest,
        qualification_artifact=grant.qualification_artifact,
        original_authorization_digest=digest_json(grant.model_dump(mode="json")),
        original_execution_policy_digest=digest_json(c.state["policy"].model_dump(mode="json")),
        completed_evidence_digest=document["evidence_digest"],
        issued_at=state["now"],
        expires_at=state["now"] + timedelta(hours=1),
    )
    state["grant"] = use
    state["policy"] = inspection.ScoringConsumptionPolicy(
        enabled=True,
        ledger_identity=use.ledger_identity,
        approved_authorizations=(digest_json(use.model_dump(mode="json")),),
        allowed_purposes=("campaign-report",),
    )
    kwargs = dict(
        ledger=c.ledger,
        campaign_artifacts=c.frozen_store,
        output_artifacts=c.output,
        authority=c.authority,
        original_authorization=grant,
        original_execution_policy=c.state["policy"],
        consumption_authorization_provider=lambda: state["grant"],
        consumption_policy_provider=lambda: state["policy"],
        clock=lambda: state["now"],
    )
    return SimpleNamespace(
        state=state,
        document=document,
        kwargs=kwargs,
        read=lambda: inspection.validate_completed_scoring_consumption(c.task, **kwargs),
    )


def snapshot(c):
    with c.ledger.engine.connect() as conn:
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
        raise AssertionError("Inspection attempted an effect")

    monkeypatch.setattr(StructuredModel, "generate", denied)
    monkeypatch.setattr("agentic_delivery.integrations.model.secret", denied)
    monkeypatch.setattr(ArtifactStore, "put", denied)
    monkeypatch.setattr(harness, "DockerRunner", denied)
    monkeypatch.setattr("agentic_delivery.execution.docker.DockerRunner.__init__", denied)
    for name in (
        "create_account",
        "reserve",
        "reserve_infrastructure",
        "settle",
        "settle_infrastructure",
        "checkpoint",
        "record_observation",
    ):
        monkeypatch.setattr(c.ledger, name, denied)


def approve(data):
    data.state["policy"] = data.state["policy"].model_copy(
        update={
            "approved_authorizations": (digest_json(data.state["grant"].model_dump(mode="json")),)
        }
    )


def rebind(c, data):
    document = copy.deepcopy(data.document)
    for stage in STAGES:
        row = c.ledger.operation_receipt(
            c.attempt.account_id, c.attempt.account_id + ":campaign-scoring-v2:" + stage
        )
        document["operation_receipt_digests"][stage] = row["receipt_digest"]
        if stage != "preflight":
            summary = row["result"]["scoring_result"]
            document["result"][stage] = summary
            document["test_receipt_artifacts"][stage] = summary["commands"][0]["artifact_digest"]
    document.pop("evidence_digest")
    data.state["grant"] = data.state["grant"].model_copy(
        update={"completed_evidence_digest": digest_json(document)}
    )
    approve(data)


@pytest.mark.parametrize("failure", [False, True])
async def test_completed_read_after_execution_expiry_has_no_effects(
    controlled_scoring, monkeypatch, failure
):
    c = controlled_scoring
    if failure:
        c.state["report_fault"] = "call-failure"
    data = await completed(c)
    c.state["now"] = data.state["now"]
    with pytest.raises(ScoringFailure):
        validate_completed_scoring(
            c.task,
            c.candidate,
            authority=c.authority,
            execution=c.create(),
            output_artifacts=c.output,
        )
    before, calls = snapshot(c), list(c.calls)
    deny_effects(c, monkeypatch)
    result = data.read()
    assert result.completed_evidence_digest == data.document["evidence_digest"]
    assert result.deterministic_passed is (not failure)
    assert result.strict_success is False
    assert "OWNED_OUTPUT_NOT_FOR_MODEL" not in result.model_dump_json()
    assert before == snapshot(c) and calls == c.calls


@pytest.mark.parametrize(
    "field",
    [
        "account_id",
        "ledger_identity",
        "campaign_artifact",
        "ordinal",
        "phase",
        "attempt_binding_artifact",
        "scoring_binding_artifact",
        "candidate_artifact",
        "candidate_digest",
        "task_manifest_digest",
        "qualification_artifact",
        "original_authorization_digest",
        "original_execution_policy_digest",
        "completed_evidence_digest",
        "expires_at",
        "purpose",
    ],
)
async def test_exact_finite_current_grant_required(controlled_scoring, monkeypatch, field):
    c = controlled_scoring
    data = await completed(c)
    value = {
        "account_id": "different",
        "ordinal": 9999,
        "phase": "test",
        "expires_at": data.state["now"],
        "purpose": "deterministic-scoring",
    }.get(field, "f" * 64)
    data.state["grant"] = data.state["grant"].model_copy(update={field: value})
    approve(data)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()


@pytest.mark.parametrize(
    "change", ["policy", "qualification", "settings", "current-calibration", "mid-read"]
)
async def test_current_authority_and_calibration_required(controlled_scoring, monkeypatch, change):
    c = controlled_scoring
    data = await completed(c)
    if change == "policy":
        data.state["policy"] = data.state["policy"].model_copy(update={"enabled": False})
    elif change == "qualification":
        c.state["revoked"] = True
    elif change == "settings":
        c.state["settings"] = c.state["settings"].model_copy(update={"admissions_enabled": False})
    else:
        original = HistoricalTask.validate_qualification
        calls = 0

        def admitted(*args, **kwargs):
            nonlocal calls
            calls += 1
            value = original(*args, **kwargs)
            if change == "current-calibration":
                value.calibration_evidence_artifact = "f" * 64
            elif calls > 3:
                raise ValueError("Owned current-use expiry")
            return value

        monkeypatch.setattr(HistoricalTask, "validate_qualification", admitted)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "unknown",
        "extra",
        "future",
        "backward",
        "reservation",
        "rate",
        "preflight",
        "nonce",
        "duplicate-nonce",
        "snapshot",
        "argv",
        "collection",
        "missing-phase",
    ],
)
async def test_fully_rebound_bad_receipts_denied(controlled_scoring, monkeypatch, mutation):
    c = controlled_scoring
    data = await completed(c)
    stage = "preflight" if mutation == "preflight" else "acceptance"
    identity = c.attempt.account_id + ":campaign-scoring-v2:" + stage
    row = c.ledger.operation_receipt(c.attempt.account_id, identity)
    updates = {}
    if mutation == "missing":
        with c.ledger.engine.begin() as conn:
            conn.execute(
                delete(execution_store.operations).where(
                    execution_store.operations.c.id == identity
                )
            )
    elif mutation == "extra":
        with c.ledger.engine.begin() as conn:
            raw = dict(
                conn.execute(
                    select(execution_store.operations).where(
                        execution_store.operations.c.id == identity
                    )
                )
                .mappings()
                .one()
            )
            raw["id"] += ":extra"
            conn.execute(execution_store.operations.insert().values(**raw))
    elif mutation == "unknown":
        updates["status"] = "RESERVED"
        updates["settled_at"] = None
    elif mutation == "future":
        updates["settled_at"] = "2099-01-01T00:00:00+00:00"
    elif mutation == "backward":
        updates["created_at"] = "1999-01-01T00:00:00+00:00"
    elif mutation == "reservation":
        updates["reserved_microdollars"] = row["reserved_microdollars"] + 1
    else:
        stored = copy.deepcopy(row["result"])
        if mutation == "rate":
            stored[execution_store.INFRA_RESERVATION]["microdollars_per_second"] = 2
            stored[execution_store.INFRA_RECEIPT]["microdollars_per_second"] = 2
        elif mutation == "preflight":
            stored["scoring_result"] = {"invented_probe": True}
        else:
            summary = stored["scoring_result"]
            receipt = json.loads(c.output.get(summary["commands"][0]["artifact_digest"]))
            if mutation == "nonce":
                receipt["verification_binding"].pop("nonce")
                receipt["verification_report"]["binding"].pop("nonce")
            elif mutation == "duplicate-nonce":
                regression = c.ledger.operation_receipt(
                    c.attempt.account_id, c.attempt.account_id + ":campaign-scoring-v2:regression"
                )
                other = json.loads(
                    c.output.get(
                        regression["result"]["scoring_result"]["commands"][0]["artifact_digest"]
                    )
                )
                receipt["verification_binding"]["nonce"] = receipt["verification_report"][
                    "binding"
                ]["nonce"] = other["verification_binding"]["nonce"]
            elif mutation == "snapshot":
                receipt["snapshot_digest"] = "f" * 64
            elif mutation == "argv":
                receipt["argv"] = ["python", "-m", "pytest", "tests/test_different.py"]
            elif mutation == "collection":
                receipt["verification_report"]["collected"] = []
            elif mutation == "missing-phase":
                receipt["verification_report"]["phases"].pop()
            summary["commands"][0]["artifact_digest"] = put(c.output, receipt)
        updates["result"] = stored
    if updates:
        with c.ledger.engine.begin() as conn:
            conn.execute(
                update(execution_store.operations)
                .where(execution_store.operations.c.id == identity)
                .values(**updates)
            )
    if mutation != "missing":
        rebind(c, data)
    before = snapshot(c)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()
    assert before == snapshot(c)


async def test_unrelated_later_settled_stage_does_not_grant_or_block_read(
    controlled_scoring, monkeypatch
):
    c = controlled_scoring
    data = await completed(c)
    c.ledger.reserve(c.attempt.account_id, "owned-later", 1, 1, 1)
    c.ledger.settle("owned-later", cost=1, input_tokens=1, output_tokens=1, result={"owned": True})
    before = snapshot(c)
    deny_effects(c, monkeypatch)
    assert data.read().deterministic_passed
    assert before == snapshot(c)


@pytest.mark.parametrize("original", ["original_authorization", "original_execution_policy"])
async def test_original_documents_cannot_be_renewed(controlled_scoring, monkeypatch, original):
    c = controlled_scoring
    data = await completed(c)
    proof = data.kwargs[original]
    field, value = (
        ("expires_at", proof.expires_at + timedelta(hours=1))
        if original == "original_authorization"
        else ("microdollars_per_second", 2)
    )
    data.kwargs[original] = proof.model_copy(update={field: value})
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()


async def test_duplicate_ledger_target_is_not_currently_authorized(
    controlled_scoring, monkeypatch, tmp_path
):
    c = controlled_scoring
    data = await completed(c)
    other = execution_store.EvaluationExecutionStore(
        "sqlite:///" + (tmp_path / "delivery_eval_duplicate.db").as_posix()
    )
    data.kwargs["ledger"] = other
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()
    other.engine.dispose()


async def test_overlapping_artifact_scope_denied_before_candidate_read(
    controlled_scoring, monkeypatch
):
    c = controlled_scoring
    data = await completed(c)
    data.kwargs["output_artifacts"] = c.protected
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()


@pytest.mark.parametrize("checkpoint", ["campaign-attempt-v1", SCORING_CHECKPOINT])
async def test_rewritten_checkpoint_chronology_denied(controlled_scoring, monkeypatch, checkpoint):
    c = controlled_scoring
    data = await completed(c)
    with c.ledger.engine.begin() as conn:
        conn.execute(
            update(execution_store.checkpoints)
            .where(
                execution_store.checkpoints.c.account_id == c.attempt.account_id,
                execution_store.checkpoints.c.stage == checkpoint,
            )
            .values(created_at="2099-01-01T00:00:00+00:00")
        )
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()


async def test_qualification_expiry_is_not_replaced_with_execution_time(
    controlled_scoring, monkeypatch
):
    c = controlled_scoring
    data = await completed(c)
    c.state["now"] = data.state["now"]
    old = HistoricalTask.validate_qualification
    observed = []

    def admitted(*args, **kwargs):
        now = kwargs["authority"].clock()
        observed.append(now)
        if now >= c.attempt.deadline:
            raise ValueError("Owned current qualification expired")
        return old(*args, **kwargs)

    monkeypatch.setattr(HistoricalTask, "validate_qualification", admitted)
    deny_effects(c, monkeypatch)
    with pytest.raises(inspection.ScoringInspectionFailure):
        data.read()
    assert observed and all(now >= c.attempt.deadline for now in observed)
