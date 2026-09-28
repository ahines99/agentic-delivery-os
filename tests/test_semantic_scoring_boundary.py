"""Concrete scoring-ledger reader; its owned fixture replaces qualification and Docker."""

# Ruff permits explicitly imported pytest fixtures to be named by test parameters.
# ruff: noqa: F811

import json

import pytest
from test_campaign_scoring import (  # noqa: F401
    campaign_scoring,
    campaign_seed,
    controlled_scoring,
)

from agentic_delivery.evaluation import harness, semantic_scoring
from agentic_delivery.storage.store import digest_json


async def test_semantic_boundary_reuses_settled_shared_account_read_only(
    controlled_scoring, monkeypatch
):
    case = controlled_scoring
    result = await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=case.create(),
    )
    assert result["passed"]
    before = case.ledger.account(case.attempt.account_id)
    calls = list(case.calls)

    def forbidden(*args, **kwargs):
        pytest.fail("Semantic evidence reading must not allocate or execute")

    for name in ("create_account", "checkpoint", "reserve", "reserve_infrastructure"):
        monkeypatch.setattr(case.ledger, name, forbidden)
    monkeypatch.setattr(case.output, "put", forbidden)
    monkeypatch.setattr(harness, "DockerRunner", forbidden)
    chain = semantic_scoring._completed(
        case.task,
        case.candidate,
        authority=case.authority,
        execution=case.create(),
        output_artifacts=case.output,
    )
    assert chain["result"] == result
    assert chain["candidate_digest"] == digest_json(case.candidate)
    assert chain["account_id"] == case.attempt.account_id
    assert set(chain["operation_receipt_digests"]) == {"preflight", "acceptance", "regression"}
    assert "OWNED_OUTPUT_NOT_FOR_MODEL" not in json.dumps(chain)
    assert case.calls == calls
    assert case.ledger.account(case.attempt.account_id) == before
    with pytest.raises(semantic_scoring.SemanticScoringFailure):
        semantic_scoring._completed(
            case.task,
            case.candidate,
            authority=case.authority,
            execution=object(),
            output_artifacts=case.output,
        )
