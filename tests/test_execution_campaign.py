"""Owned contract fixtures; no real corpus admission or campaign execution."""

import json

import pytest
from pydantic import ValidationError
from test_evaluation_campaign import corpus as campaign_corpus
from test_evaluation_campaign import corpus_seed as campaign_corpus_seed
from test_evaluation_campaign import put

from agentic_delivery.evaluation.campaign import (
    CampaignFailure,
    CampaignSpecification,
    ExecutionCampaign,
    FrozenCampaign,
    freeze_campaign,
    freeze_execution_campaign,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest


@pytest.fixture(scope="module")
def corpus_seed(tmp_path_factory):
    return campaign_corpus_seed.__wrapped__(tmp_path_factory)


@pytest.fixture
def corpus(corpus_seed, tmp_path, monkeypatch):
    return campaign_corpus.__wrapped__(corpus_seed, tmp_path, monkeypatch)


def lower_execution_limits(fixture):
    tasks, spec, store, output = fixture
    document = spec.model_dump(mode="json")
    for reference in document["arms"]:
        arm = json.loads(store.get(reference["configuration_artifact"]))
        arm["limits"].update(
            model_microdollars=1_000_000,
            input_tokens=50_000,
            output_tokens=10_000,
            repair_rounds=0,
        )
        reference["configuration_artifact"] = put(store, arm)
    return tasks, CampaignSpecification.model_validate(document), store, output


def freeze(fixture):
    tasks, spec, store, output = fixture
    return freeze_execution_campaign(
        tasks, spec, store, output, authority=store._test_campaign_authority
    )


def test_explicit_execution_profile_preserves_admitted_task_bytes(corpus):
    fixture = lower_execution_limits(corpus)
    tasks, spec, store, output = fixture
    originals = tuple(task.model_dump_json() for task in tasks)
    result, digest = freeze(fixture)
    assert result.schema_version == 3
    assert result.execution_budget_basis == "FROZEN_ARM_LIMITS_SEPARATE_FROM_QUALIFICATION"
    assert result.execution_budget_scope == "BUILDER_REVIEW_AND_FINAL_SCORING"
    assert tuple(task.model_dump_json() for task in tasks) == originals
    by_id = {task.id: task for task in tasks}
    assert all(
        frozen.task_manifest_digest
        == qualification_task_digest(by_id[frozen.task_id].model_dump(mode="json"))
        and frozen.qualification_artifact == by_id[frozen.task_id].qualification_artifact
        for frozen in result.tasks
    )
    assert result.specification == spec
    assert result.attempt_cost_ceiling_microdollars == 2_000_000
    assert result.worst_case_microdollars == (
        (result.primary_attempts + result.stability_attempts) * 2_000_000
        + spec.preparation_reservation_microdollars
    )
    assert result.spend_authorized is False
    assert result.status == "PREREGISTERED_NOT_EXECUTED"
    assert ExecutionCampaign.model_validate_json(output.get(digest)) == result
    assert freeze(fixture) == (result, digest)
    with pytest.raises(ValidationError):
        FrozenCampaign.model_validate_json(output.get(digest))


def test_v2_does_not_silently_reinterpret_different_task_budgets(corpus):
    tasks, spec, store, output = lower_execution_limits(corpus)
    with pytest.raises(CampaignFailure, match="Task resource ceilings differ"):
        freeze_campaign(tasks, spec, store, output, authority=store._test_campaign_authority)
    assert not list(output.root.rglob("*"))


def test_v3_still_requires_concrete_current_authority(corpus):
    tasks, spec, store, output = lower_execution_limits(corpus)
    with pytest.raises(CampaignFailure, match="Concrete current qualification authority"):
        freeze_execution_campaign(tasks, spec, store, output)
    assert not list(output.root.rglob("*"))


@pytest.mark.parametrize("violation", ["parity", "cap", "corpus"])
def test_execution_profile_does_not_weaken_existing_campaign_gates(corpus, violation):
    tasks, spec, store, output = lower_execution_limits(corpus)
    document = spec.model_dump(mode="json")
    if violation == "parity":
        reference = document["arms"][1]
        arm = json.loads(store.get(reference["configuration_artifact"]))
        arm["limits"]["input_tokens"] -= 1
        reference["configuration_artifact"] = put(store, arm)
    elif violation == "cap":
        document["cap_microdollars"] = 1
    else:
        tasks = tasks[:-1]
    with pytest.raises(CampaignFailure):
        freeze((tasks, CampaignSpecification.model_validate(document), store, output))
    assert not list(output.root.rglob("*"))


def test_late_current_authority_refusal_leaves_no_v3_artifact(corpus, monkeypatch):
    fixture = lower_execution_limits(corpus)
    tasks, _, _, output = fixture
    original = HistoricalTask.validate_qualification

    def revoked(self, *args, **kwargs):
        if self.id == tasks[-1].id:
            raise ValueError("Owned current authority revocation")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HistoricalTask, "validate_qualification", revoked)
    with pytest.raises(CampaignFailure):
        freeze(fixture)
    assert not list(output.root.rglob("*"))
