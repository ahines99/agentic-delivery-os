"""Current custom path controls bind scoring and completed-evidence reads."""

# ruff: noqa: F401, F811
import copy
import json

import pytest
from sqlalchemy import update
from test_campaign_scoring import campaign_scoring, campaign_seed, controlled_scoring, put
from test_campaign_scoring_inspection import completed, deny_effects, rebind, snapshot

from agentic_delivery.evaluation import execution_store, harness
from agentic_delivery.evaluation.campaign_scoring import SCORING_CHECKPOINT
from agentic_delivery.evaluation.campaign_scoring_inspection import ScoringInspectionFailure
from agentic_delivery.storage.store import digest_json


def protect(c, paths):
    settings = c.state["settings"]
    repository = settings.repository(c.task.item.repository)
    c.state["settings"] = settings.model_copy(
        update={"repositories": (repository.model_copy(update={"protected_paths": paths}),)}
    )
    c.state["grant"] = c.state["grant"].model_copy(
        update={
            "execution_config_digest": c.state["settings"].execution_digest(repository.id),
            "candidate_digest": digest_json(c.candidate),
        }
    )


@pytest.mark.parametrize(
    "action,patterns",
    [
        ("modify", ("app.py",)),
        ("delete", ("app.py",)),
        ("rename", ("app.py",)),
        ("add", ("governed/",)),
    ],
)
async def test_custom_protected_candidate_refused_before_all_effects(
    controlled_scoring, monkeypatch, action, patterns
):
    c = controlled_scoring
    if action == "delete":
        c.candidate = {"other.py": "VALUE = 2\n"}
    elif action == "rename":
        c.candidate = {"renamed.py": c.candidate["app.py"]}
    elif action == "add":
        c.candidate["governed/policy.txt"] = "owned candidate addition\n"
    protect(c, patterns)
    before = snapshot(c)
    deny_effects(c, monkeypatch)
    with pytest.raises(ValueError, match="Candidate changed protected source"):
        await harness.score_campaign_candidate(
            c.task, c.candidate, c.protected, c.output, authority=c.authority, execution=c.create()
        )
    assert c.calls == [] and snapshot(c) == before


async def test_sibling_prefix_is_not_mistaken_for_custom_directory(controlled_scoring):
    c = controlled_scoring
    c.candidate["governed_extra/notes.txt"] = "owned allowed file\n"
    protect(c, ("governed/",))
    result = await harness.score_campaign_candidate(
        c.task, c.candidate, c.protected, c.output, authority=c.authority, execution=c.create()
    )
    assert result["passed"] and len(c.calls) == 3


async def test_complete_rebound_scoring_evidence_cannot_bypass_custom_path_policy(
    controlled_scoring, monkeypatch
):
    c = controlled_scoring
    data = await completed(c)
    # Construct a fully rebound owned receipt chain as an external candidate could
    # previously present. No stale settings digest is allowed to cause the denial.
    protect(c, ("app.py",))
    grant = c.state["grant"]
    data.kwargs["original_authorization"] = grant
    binding = json.loads(c.output.get(data.state["grant"].scoring_binding_artifact))
    binding["authorization_digest"] = digest_json(grant.model_dump(mode="json"))
    binding_ref = put(c.output, binding)
    with c.ledger.engine.begin() as conn:
        conn.execute(
            update(execution_store.checkpoints)
            .where(
                execution_store.checkpoints.c.account_id == c.attempt.account_id,
                execution_store.checkpoints.c.stage == SCORING_CHECKPOINT,
            )
            .values(artifact_digest=binding_ref)
        )
    for stage in ("preflight", "acceptance", "regression"):
        identity = c.attempt.account_id + ":campaign-scoring-v2:" + stage
        row = c.ledger.operation_receipt(c.attempt.account_id, identity)
        stored = copy.deepcopy(row["result"])
        value = digest_json({"campaign_scoring": digest_json(binding), "stage": stage})
        stored[execution_store.INFRA_RESERVATION]["binding_digest"] = value
        stored[execution_store.INFRA_RECEIPT]["binding_digest"] = value
        with c.ledger.engine.begin() as conn:
            conn.execute(
                update(execution_store.operations)
                .where(execution_store.operations.c.id == identity)
                .values(result=stored)
            )
    data.document["authorization_digest"] = binding["authorization_digest"]
    data.document["scoring_binding_artifact"] = binding_ref
    data.state["grant"] = data.state["grant"].model_copy(
        update={
            "original_authorization_digest": binding["authorization_digest"],
            "scoring_binding_artifact": binding_ref,
        }
    )
    rebind(c, data)
    before, calls = snapshot(c), list(c.calls)
    material = harness._scoring_material
    observed = []

    def checked_material(*args, **kwargs):
        try:
            return material(*args, **kwargs)
        except ValueError as error:
            observed.append(str(error))
            raise

    monkeypatch.setattr(
        "agentic_delivery.evaluation.campaign_scoring_inspection._scoring_material",
        checked_material,
    )
    deny_effects(c, monkeypatch)
    with pytest.raises(ScoringInspectionFailure):
        data.read()
    assert observed == ["Candidate changed protected source tests or execution controls"]
    assert snapshot(c) == before and c.calls == calls


@pytest.mark.parametrize("path", ["Dockerfile", ".github/workflows/changed.yml"])
async def test_empty_custom_list_cannot_remove_fixed_controls(
    controlled_scoring, monkeypatch, path
):
    c = controlled_scoring
    c.candidate[path] = "owned disallowed control\n"
    protect(c, ())
    before = snapshot(c)
    deny_effects(c, monkeypatch)
    with pytest.raises(ValueError, match="Candidate changed protected source"):
        await harness.score_campaign_candidate(
            c.task, c.candidate, c.protected, c.output, authority=c.authority, execution=c.create()
        )
    assert snapshot(c) == before and not c.calls
