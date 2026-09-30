"""Owned callback checks for pending manual criteria, never human acceptance evidence."""

import json

import pytest
from test_candidate_engine import fixture as candidate_fixture
from test_candidate_engine import proposal, review_result

from agentic_delivery.agents.candidate_engine import iterate_candidate
from agentic_delivery.agents.contracts import CriterionTests
from agentic_delivery.domain.models import AcceptanceCriterion

fixture = candidate_fixture


@pytest.mark.parametrize("only_manual", [False, True])
@pytest.mark.parametrize("verdict", ["UNKNOWN", "PASS", "FAIL", "missing"])
async def test_manual_review_cannot_be_satisfied_by_model_or_test(fixture, only_manual, verdict):
    item, plan, base, candidate, repository = fixture
    manual = AcceptanceCriterion(
        id="AC-M", description="Owner checks presentation", verification_type="manual_review"
    )
    criteria = (manual,) if only_manual else (*item.acceptance_criteria, manual)
    item = item.model_copy(update={"acceptance_criteria": criteria})
    plan = plan.model_copy(update={"criteria": criteria})
    commands_seen = []

    async def build(iteration, context):
        assert context["ticket"]["acceptance_criteria"][-1]["verification_type"] == "manual_review"
        result = proposal(base, candidate)
        return result.model_copy(update={"criterion_tests": ()}) if only_manual else result

    async def review(iteration, context):
        assert set(context["criterion_evidence"]) == (set() if only_manual else {"AC-1"})
        result = review_result(True)
        verdicts = [] if only_manual else list(result.criterion_verdicts)
        if verdict != "missing":
            verdicts.append({"criterion_id": "AC-M", "result": verdict})
        return type(result).model_validate(
            {**result.model_dump(mode="json"), "criterion_verdicts": verdicts}
        )

    async def verify(files, commands):
        commands_seen.append(tuple(command.id for command in commands))
        return {"passed": True}

    outcome = await iterate_candidate(
        item,
        plan,
        base,
        commands=repository.commands,
        protected_paths=repository.protected_paths,
        repair_rounds=0,
        independent_review=True,
        build=build,
        review=review,
        verify=verify,
        authorization_check=lambda: None,
        allow_manual=True,
    )
    assert outcome.status == ("MANUAL_REVIEW_PENDING" if verdict == "UNKNOWN" else "FAILED")
    assert json.loads(outcome.candidate_json) == candidate
    assert commands_seen[:2] == [tuple(c.id for c in repository.commands)] * 2
    assert not any("AC-M" in commands for commands in commands_seen)
    if verdict == "UNKNOWN":
        assert json.loads(outcome.evidence_json)["pending_manual_criteria"] == ["AC-M"]


@pytest.mark.parametrize("allow_manual,independent", [(False, True), (False, False), (True, False)])
async def test_default_and_builder_only_profiles_still_refuse_manual(
    fixture, allow_manual, independent
):
    item, plan, base, _, repository = fixture
    item = item.model_copy(
        update={
            "acceptance_criteria": (
                AcceptanceCriterion(
                    id="AC-M", description="Owned check", verification_type="manual_review"
                ),
            )
        }
    )

    async def no_effect(*args):
        pytest.fail("Manual criteria reached an unauthorized callback")

    with pytest.raises(ValueError):
        await iterate_candidate(
            item,
            plan,
            base,
            commands=repository.commands,
            protected_paths=repository.protected_paths,
            repair_rounds=0,
            independent_review=independent,
            build=no_effect,
            review=no_effect if independent else None,
            verify=no_effect,
            authorization_check=lambda: None,
            allow_manual=allow_manual,
        )


async def test_builder_cannot_map_manual_acceptance_to_pytest(fixture):
    item, plan, base, candidate, repository = fixture
    item = item.model_copy(
        update={
            "acceptance_criteria": (
                *item.acceptance_criteria,
                AcceptanceCriterion(
                    id="AC-M", description="Owned check", verification_type="manual_review"
                ),
            )
        }
    )

    async def build(*args):
        result = proposal(base, candidate)
        return result.model_copy(
            update={
                "criterion_tests": (
                    *result.criterion_tests,
                    CriterionTests(criterion_id="AC-M", tests=("tests/test_new.py::test_new",)),
                )
            }
        )

    async def verify(*args):
        return {"passed": True}

    async def review(*args):
        pytest.fail("A manual-to-test mapping reached review")

    with pytest.raises(ValueError, match="test mapping"):
        await iterate_candidate(
            item,
            plan,
            base,
            commands=repository.commands,
            protected_paths=repository.protected_paths,
            repair_rounds=0,
            independent_review=True,
            build=build,
            review=review,
            verify=verify,
            authorization_check=lambda: None,
            allow_manual=True,
        )
