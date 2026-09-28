"""Synthetic contract fixtures only; no actual corpus qualification or model calls."""

import copy
import json

import pytest
from test_qualification import (
    historical_task,
    make_review,
    put,
)
from test_qualification import (
    records as qualification_records,
)

from agentic_delivery.evaluation.campaign import (
    ArmConfiguration,
    CampaignFailure,
    CampaignSpecification,
    freeze_campaign,
    select_stability_tasks,
)
from agentic_delivery.evaluation.cli import main as evaluation_main
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.fixture(scope="module")
def corpus_seed(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("synthetic-campaign-corpus")
    store, original, initial_spec = qualification_records.__wrapped__(tmp_path / "protected")
    output = ArtifactStore(tmp_path / "frozen")
    tasks = []
    for split in ("development", "validation", "test"):
        for number in range(10):
            record, spec = copy.deepcopy(original), copy.deepcopy(initial_spec)
            record["task_id"] = spec["task_id"] = f"synthetic-{split}-{number}"
            spec["split"] = split
            spec["family"] = f"fixture-family-{split}-{number}"
            repository = f"fixture/{split}"
            spec["provenance"]["repository"] = repository
            spec["provenance"]["issue_url"] = f"https://github.com/{repository}/issues/{number + 1}"
            spec["provenance"]["license_url"] = (
                f"https://github.com/{repository}/blob/{'a' * 40}/LICENSE"
            )
            spec["task_spec"]["repository"] = repository
            record["review_records"] = [
                make_review(store, record, spec, stage) for stage in ("qualifier_a", "qualifier_b")
            ]
            tasks.append(historical_task((store, record, spec)))
    evidence = store.put(b"Explicitly synthetic configuration fixture; not a completed calibration")
    limits = {
        **tasks[0].budget.model_dump(),
        "infrastructure_microdollars": 1_000_000,
        "transport_retries": 2,
    }
    model = {
        "provider": "openai",
        "model": "synthetic-no-provider-call",
        "input_microdollars_per_million": 1,
        "output_microdollars_per_million": 1,
        "rate_card_version": "synthetic",
        "max_output_tokens": 100,
    }
    configs = []
    for arm in ("A", "B"):
        config = ArmConfiguration.model_validate(
            {
                "schema_version": 1,
                "arm": arm,
                "model": model,
                "limits": limits,
                "policy_digest": evidence,
                "tool_permissions_digest": evidence,
                "builder_prompt_digest": evidence,
                "review_prompt_digest": evidence if arm == "B" else None,
                "independent_review": arm == "B",
                "context_digest": None,
            }
        )
        configs.append(config)
    calibration = {
        "schema_version": 1,
        "rubric_artifact": evidence,
        "split": "development",
        "known_pass_receipts": [store.put(b"Synthetic known-pass record")],
        "known_fail_receipts": [store.put(b"Synthetic known-fail record")],
        "tamper_receipts": [store.put(b"Synthetic tamper record")],
        "mandatory_safety_passed": True,
        "mandatory_false_ready_passed": True,
    }
    spec = CampaignSpecification.model_validate(
        {
            "schema_version": 1,
            "protocol_version": "agentic-historical-v1",
            "campaign_id": "synthetic-campaign",
            "dataset_version": "synthetic-v1",
            "scoring_code_commit": "f" * 40,
            "rubric_artifact": evidence,
            "calibration_artifact": put(store, calibration),
            "selection_ledger_artifact": evidence,
            "preregistered_at": "2026-09-28T12:00:00Z",
            "execution_started": False,
            "seed": 101,
            "arms": [
                {"arm": c.arm, "configuration_artifact": put(store, c.model_dump(mode="json"))}
                for c in configs
            ],
            "stability_task_ids": select_stability_tasks(tuple(tasks), 101),
            "cap_microdollars": 1_000_000_000,
            "preparation_reservation_microdollars": 100_000_000,
        }
    )
    return tuple(tasks), spec, store, output


@pytest.fixture
def corpus(corpus_seed, tmp_path):
    tasks, spec, store, _ = corpus_seed
    return tasks, spec, store, ArtifactStore(tmp_path / "frozen")


def update_spec(corpus, **updates):
    tasks, spec, store, output = corpus
    return (
        tasks,
        CampaignSpecification.model_validate({**spec.model_dump(mode="json"), **updates}),
        store,
        output,
    )


def replace_arm(corpus, index, **updates):
    tasks, spec, store, output = corpus
    arms = spec.model_dump(mode="json")["arms"]
    config = json.loads(store.get(arms[index]["configuration_artifact"]))
    config.update(updates)
    arms[index]["configuration_artifact"] = put(store, config)
    return update_spec(corpus, arms=arms)


def assert_no_output(corpus):
    assert list(corpus[3].root.rglob("*")) == []


def test_freeze_is_deterministic_paired_and_contains_no_protected_answers(corpus):
    tasks, spec, store, output = corpus
    frozen, digest = freeze_campaign(*corpus)
    reversed_frozen, same_digest = freeze_campaign(tuple(reversed(tasks)), spec, store, output)
    assert frozen == reversed_frozen
    assert digest == same_digest
    assert frozen.primary_attempts == 60
    assert frozen.stability_attempts == 24
    assert len(frozen.schedule) == 84
    assert frozen.worst_case_microdollars == 604_000_000
    assert frozen.spend_authorized is False
    assert frozen.calibration_verified is False
    assert frozen.heldout_repositories == ("https://github.com/fixture/test",)
    split_rank = {"development": 0, "validation": 1, "test": 2}
    phases = [split_rank[entry.split] for entry in frozen.schedule]
    assert phases == sorted(phases)
    for index in range(0, len(frozen.schedule), 2):
        first, second = frozen.schedule[index : index + 2]
        assert {first.arm, second.arm} == {"A", "B"}
        assert (first.task_id, first.seed, first.repeat) == (
            second.task_id,
            second.seed,
            second.repeat,
        )
    for task in tasks:
        attempts = [entry for entry in frozen.schedule if entry.task_id == task.id]
        assert len(attempts) == (6 if task.id in spec.stability_task_ids else 2)
        assert sum(entry.kind == "primary" for entry in attempts) == 2
        if task.id in spec.stability_task_ids:
            assert len({entry.seed for entry in attempts}) == 3
    serialized = output.get(digest).decode()
    assert "VALUE =" not in serialized
    assert "oracle_artifact" not in serialized
    assert "reference_snapshot_artifact" not in serialized
    assert "::test_" not in serialized
    assert "provider_request_id" not in serialized


@pytest.mark.parametrize(
    "mutation",
    ["too_few", "unequal", "duplicate_id", "duplicate_issue", "family", "no_heldout", "two_repos"],
)
def test_dataset_shape_failures_leave_no_frozen_output(corpus, mutation):
    tasks, spec, store, output = corpus
    changed = list(tasks)
    if mutation == "too_few":
        changed = changed[:-3]
    elif mutation == "unequal":
        changed[-1] = changed[-1].model_copy(update={"split": "validation"})
    elif mutation == "duplicate_id":
        changed[-1] = changed[-1].model_copy(update={"id": changed[-2].id})
    elif mutation == "duplicate_issue":
        changed[-1] = changed[-1].model_copy(update={"issue_url": changed[-2].issue_url})
    elif mutation == "family":
        changed[-1] = changed[-1].model_copy(update={"family": changed[0].family})
    elif mutation == "no_heldout":
        changed[0] = changed[0].model_copy(update={"repository_url": changed[-1].repository_url})
    else:
        changed = [
            t.model_copy(update={"repository_url": "https://github.com/fixture/shared"})
            if t.split != "test"
            else t
            for t in changed
        ]
    with pytest.raises(CampaignFailure):
        freeze_campaign(tuple(changed), spec, store, output)
    assert_no_output(corpus)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_A",
        "missing_B",
        "duplicate",
        "C_without_context",
        "wrong_model",
        "wrong_limits",
        "wrong_policy",
        "wrong_tools",
        "wrong_prompt",
        "B_without_review",
        "A_with_review",
        "missing_artifact",
    ],
)
def test_arm_configuration_mismatch_is_not_frozen(corpus, mutation):
    _, spec, store, _ = corpus
    arms = spec.model_dump(mode="json")["arms"]
    if mutation in {"missing_A", "missing_B", "duplicate"}:
        replacement = "B" if mutation == "missing_A" else "A"
        arms[0 if mutation == "missing_A" else 1]["arm"] = replacement
        changed = update_spec(corpus, arms=arms)
    elif mutation == "C_without_context":
        config = json.loads(store.get(arms[1]["configuration_artifact"]))
        config["arm"] = "C"
        arms.append({"arm": "C", "configuration_artifact": put(store, config)})
        changed = update_spec(corpus, arms=arms)
    elif mutation == "wrong_model":
        config = json.loads(store.get(arms[1]["configuration_artifact"]))
        changed = replace_arm(corpus, 1, model={**config["model"], "model": "other"})
    elif mutation == "wrong_limits":
        config = json.loads(store.get(arms[1]["configuration_artifact"]))
        changed = replace_arm(
            corpus, 1, limits={**config["limits"], "model_microdollars": 4_000_000}
        )
    elif mutation in {"wrong_policy", "wrong_tools", "wrong_prompt"}:
        field = {
            "wrong_policy": "policy_digest",
            "wrong_tools": "tool_permissions_digest",
            "wrong_prompt": "builder_prompt_digest",
        }[mutation]
        changed = replace_arm(corpus, 1, **{field: store.put(b"different synthetic config")})
    elif mutation == "B_without_review":
        changed = replace_arm(corpus, 1, independent_review=False)
    elif mutation == "A_with_review":
        changed = replace_arm(corpus, 0, independent_review=True)
    else:
        arms[1]["configuration_artifact"] = "a" * 64
        changed = update_spec(corpus, arms=arms)
    with pytest.raises(CampaignFailure):
        freeze_campaign(*changed)
    assert_no_output(corpus)


def test_C_is_explicit_and_included_in_all_cost_and_attempt_totals(corpus):
    _, spec, store, _ = corpus
    arms = spec.model_dump(mode="json")["arms"]
    config = json.loads(store.get(arms[1]["configuration_artifact"]))
    config.update(arm="C", context_digest=store.put(b"synthetic AST/coverage context fixture"))
    arms.append({"arm": "C", "configuration_artifact": put(store, config)})
    frozen, _ = freeze_campaign(*update_spec(corpus, arms=arms))
    assert frozen.primary_attempts == 90
    assert frozen.stability_attempts == 36
    assert frozen.worst_case_microdollars == 856_000_000


@pytest.mark.parametrize(
    "mutation",
    [
        "insufficient_cap",
        "qualification_reservation",
        "stability_wrong",
        "stability_duplicate",
        "unqualified_last",
        "task_limits",
        "missing_calibration",
        "rubric_mismatch",
    ],
)
def test_protocol_and_qualification_failures_leave_no_partial_output(corpus, mutation):
    tasks, spec, store, output = corpus
    if mutation == "insufficient_cap":
        changed = update_spec(corpus, cap_microdollars=603_999_999)
    elif mutation == "qualification_reservation":
        changed = update_spec(corpus, preparation_reservation_microdollars=900_000_000)
    elif mutation.startswith("stability"):
        subset = list(spec.stability_task_ids)
        subset[-1] = subset[0] if mutation.endswith("duplicate") else "absent-task"
        changed = update_spec(corpus, stability_task_ids=subset)
    elif mutation == "unqualified_last":
        changed = (
            tasks[:-1] + (tasks[-1].model_copy(update={"qualification_mode": "unverified"}),),
            spec,
            store,
            output,
        )
    elif mutation == "task_limits":
        budget = tasks[-1].budget.model_copy(update={"model_microdollars": 4_000_000})
        changed = (
            tasks[:-1] + (tasks[-1].model_copy(update={"budget": budget}),),
            spec,
            store,
            output,
        )
    elif mutation == "missing_calibration":
        changed = update_spec(corpus, calibration_artifact="f" * 64)
    else:
        changed = update_spec(corpus, rubric_artifact=store.put(b"different rubric"))
    with pytest.raises(CampaignFailure):
        freeze_campaign(*changed)
    assert_no_output(corpus)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cap_microdollars", 0),
        ("cap_microdollars", 1_000_000_001),
        ("cap_microdollars", True),
        ("execution_started", True),
        ("preparation_reservation_microdollars", 0),
        ("seed", -1),
    ],
)
def test_invalid_preregistration_schema(corpus, field, value):
    with pytest.raises(ValueError):
        update_spec(corpus, **{field: value})


def test_frozen_artifact_cannot_be_written_into_protected_evidence(corpus):
    tasks, spec, store, _ = corpus
    with pytest.raises(CampaignFailure, match="disjoint"):
        freeze_campaign(tasks, spec, store, store)


@pytest.mark.parametrize(
    "mutation", ["same_role", "cross_role", "false_safety", "false_ready", "sealed_split"]
)
def test_calibration_contradictions_cannot_be_frozen(corpus, mutation):
    _, spec, store, _ = corpus
    calibration = json.loads(store.get(spec.calibration_artifact))
    if mutation == "same_role":
        calibration["known_pass_receipts"] *= 2
    elif mutation == "cross_role":
        calibration["known_fail_receipts"] = calibration["known_pass_receipts"]
    elif mutation == "false_safety":
        calibration["mandatory_safety_passed"] = False
    elif mutation == "false_ready":
        calibration["mandatory_false_ready_passed"] = False
    else:
        calibration["split"] = "test"
    changed = update_spec(corpus, calibration_artifact=put(store, calibration))
    with pytest.raises(CampaignFailure):
        freeze_campaign(*changed)
    assert_no_output(corpus)


def test_unvalidated_copy_cannot_bypass_cap_or_execution_started(corpus):
    tasks, spec, store, output = corpus
    invalid = spec.model_copy(update={"execution_started": True, "cap_microdollars": 2_000_000_000})
    with pytest.raises(CampaignFailure):
        freeze_campaign(tasks, invalid, store, output)
    assert_no_output(corpus)


def test_same_ticket_at_different_bases_does_not_expand_denominator(corpus):
    tasks, spec, store, output = corpus
    duplicate = tasks[-1].model_copy(
        update={"issue_url": tasks[-2].issue_url, "base_sha": "b" * 40}
    )
    with pytest.raises(CampaignFailure, match="historical issue"):
        freeze_campaign(tasks[:-1] + (duplicate,), spec, store, output)
    assert_no_output(corpus)


def cli_inputs(corpus, tmp_path):
    tasks, spec, _, _ = corpus
    manifest = tmp_path / "synthetic-tasks.jsonl"
    specification = tmp_path / "synthetic-specification.json"
    summary = tmp_path / "summary.json"
    manifest.write_text(
        "\n".join(t.model_dump_json(exclude_defaults=True) for t in tasks) + "\n", encoding="utf-8"
    )
    specification.write_text(spec.model_dump_json(), encoding="utf-8")
    return manifest, specification, summary


def cli_freeze(corpus, manifest, specification, summary):
    return evaluation_main(
        [
            "freeze-campaign",
            "--manifest",
            str(manifest),
            "--specification",
            str(specification),
            "--artifacts",
            str(corpus[2].root),
            "--output-artifacts",
            str(corpus[3].root),
            "--output",
            str(summary),
        ]
    )


def test_cli_freezes_synthetic_corpus_without_claiming_execution(corpus, tmp_path):
    manifest, specification, summary = cli_inputs(corpus, tmp_path)
    assert cli_freeze(corpus, manifest, specification, summary) == 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert result["status"] == "PREREGISTERED_NOT_EXECUTED"
    assert result["spend_authorized"] is False
    assert result["calibration_verified"] is False
    frozen = json.loads(corpus[3].get(result["campaign_artifact"]))
    assert len(frozen["tasks"]) == 30
    assert len(frozen["schedule"]) == 84
    assert "VALUE =" not in json.dumps(result)


@pytest.mark.parametrize("location", ["protected", "frozen", "manifest", "specification"])
def test_cli_invalid_output_does_not_write_campaign(corpus, tmp_path, location):
    manifest, specification, summary = cli_inputs(corpus, tmp_path)
    destination = {
        "protected": corpus[2].root / "summary.json",
        "frozen": corpus[3].root / "summary.json",
        "manifest": manifest,
        "specification": specification,
    }[location]
    before = destination.read_bytes() if destination.exists() else None
    with pytest.raises(SystemExit) as failure:
        cli_freeze(corpus, manifest, specification, destination)
    assert failure.value.code == 2
    assert_no_output(corpus)
    if before is not None:
        assert destination.read_bytes() == before
    else:
        assert not destination.exists()


def test_cli_incomplete_last_task_preserves_outputs(corpus, tmp_path):
    manifest, specification, summary = cli_inputs(corpus, tmp_path)
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    records[-1]["qualification_mode"] = "unverified"
    manifest.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    summary.write_bytes(b"previous summary must survive")
    with pytest.raises(SystemExit):
        cli_freeze(corpus, manifest, specification, summary)
    assert summary.read_bytes() == b"previous summary must survive"
    assert_no_output(corpus)
