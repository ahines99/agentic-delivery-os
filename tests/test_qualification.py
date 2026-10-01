"""Fabricated control-plane records test validation, never qualify real tasks."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_delivery.config import CommandProfile
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation.cli import main as evaluation_main
from agentic_delivery.evaluation.harness import HistoricalTask, load_manifest, score_candidate
from agentic_delivery.evaluation.qualification import (
    AgentReview,
    QualificationFailure,
    QualificationInput,
    QualificationRecord,
    ReviewContext,
    qualification_task_digest,
    validate_qualification,
)
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.verification import verify
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


def get(store, digest):
    return json.loads(store.get(digest))


@pytest.fixture
def records(tmp_path):
    """These receipts are explicitly synthetic fixtures, not claimed model/runtime runs."""
    store = ArtifactStore(tmp_path)
    evidence = store.put(b"Synthetic fixture: not actual rights or provider evidence")
    checks = dict.fromkeys(("rights", "risk", "runtime", "leakage", "family", "oracle"), "PASS")
    source = {"app.py": "VALUE = 1\n"}
    oracle = {
        "tests/test_behavior.py": "# synthetic oracle placeholder\n",
        "tests/test_regression.py": "# synthetic regression placeholder\n",
    }
    baseline = {**source, **oracle}
    reference = {**baseline, "app.py": "VALUE = 2\n"}
    commands = {
        suite: {
            "id": suite,
            "argv": ["python", "-m", "pytest", f"tests/test_{name}.py"],
            "expected_tests": 1,
        }
        for suite, name in (("acceptance", "behavior"), ("regression", "regression"))
    }
    nodes = {
        "acceptance": "tests/test_behavior.py::test_value",
        "regression": "tests/test_regression.py::test_existing",
    }
    image = "sha256:" + "e" * 64
    executions = []
    for variant in ("baseline", "reference"):
        files = baseline if variant == "baseline" else reference
        for suite in ("acceptance", "regression"):
            for rep in (1, 2, 3):
                fail = variant == "baseline" and suite == "acceptance"
                command = commands[suite]
                binding = {
                    "nonce": uuid4().hex,
                    "snapshot_digest": digest_json(files),
                    "command_digest": digest_json(command),
                    "argv": command["argv"],
                }
                report = {
                    "collector_version": 1,
                    "binding": binding,
                    "session_started": True,
                    "session_finished": True,
                    "main_returned": True,
                    "exit_code": int(fail),
                    "collected": [nodes[suite]],
                    "collection_errors": [],
                    "deselected": [],
                    "phases": [
                        {
                            "nodeid": nodes[suite],
                            "when": phase,
                            "outcome": "failed" if fail and phase == "call" else "passed",
                            "wasxfail": False,
                        }
                        for phase in ("setup", "call", "teardown")
                    ],
                }
                receipt = {
                    "exit_code": int(fail),
                    "stdout": "",
                    "stderr": "",
                    "elapsed_seconds": 0.1,
                    "image": image,
                    "timed_out": False,
                    "verification_report": report,
                    "report_error": None,
                    "command_id": suite,
                    "argv": command["argv"],
                    "snapshot_digest": digest_json(files),
                    "verification_binding": binding,
                    "collector_profile": "image-owned-pytest-v1",
                    "workflow_id": f"unit-fixture-{variant}-{suite}-{rep}",
                }
                executions.append(
                    {
                        "variant": variant,
                        "suite": suite,
                        "repetition": rep,
                        "receipt_artifact": put(store, receipt),
                    }
                )
    task = {"id": "synthetic-task", "qualification_artifact": "0" * 64}
    task_digest = qualification_task_digest(task)
    spec = {
        "schema_version": 1,
        "task_id": "synthetic-task",
        "task_manifest_digest": task_digest,
        "task_spec": WorkItem(
            id="fixture",
            title="Update value",
            description="Update the value.",
            repository="fixture/repo",
            risk_tier=1,
            acceptance_criteria=(
                {
                    "id": "AC-1",
                    "description": "Updated value works",
                    "verification_type": "unit_test",
                },
            ),
        ).model_dump(mode="json"),
        "provenance": {
            "repository": "fixture/repo",
            "base_sha": "a" * 40,
            "source_task_id": "synthetic-source",
            "source_url": "https://example.test/source",
            "source_revision": "b" * 40,
            "source_snapshot_artifact": put(store, source),
            "issue_url": "https://github.com/fixture/repo/issues/1",
            "license_id": "MIT",
            "license_url": f"https://github.com/fixture/repo/blob/{'a' * 40}/LICENSE",
            "license_evidence_artifact": evidence,
            "usage_authorization_artifact": evidence,
            "rights_scope": "REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
        },
        "checks": checks,
        "findings": [
            {
                "check": check,
                "status": "PASS",
                "summary": "Synthetic finding for validator tests",
                "evidence_refs": [evidence],
            }
            for check in checks
        ],
        "check_evidence": {key: evidence for key in checks},
        "risk_tier": 1,
        "family": "synthetic-family",
        "split": "development",
        "image": image,
        "baseline_snapshot_artifact": put(store, baseline),
        "reference_snapshot_artifact": put(store, reference),
        "oracle_artifact": put(store, oracle),
        "reference_patch_artifact": evidence,
        "acceptance_command": commands["acceptance"],
        "regression_command": commands["regression"],
        "behavior_nodes": [nodes["acceptance"]],
        "regression_nodes": [nodes["regression"]],
        "executions": executions,
    }
    spec_digest = put(store, spec)
    record = {
        "schema_version": 1,
        "qualification_mode": "agent",
        "task_id": "synthetic-task",
        "task_manifest_digest": task_digest,
        "qualification_input_artifact": spec_digest,
        "review_records": [],
        "adjudication_ref": None,
    }
    for stage in ("qualifier_a", "qualifier_b"):
        record["review_records"].append(make_review(store, record, spec, stage))
    return store, record, spec


def make_review(store, record, spec, stage, verdict="ADMIT", context_id=None):
    evidence = next(iter(spec["check_evidence"].values()))
    context = {
        "schema_version": 1,
        "stage": stage,
        "task_id": record["task_id"],
        "task_manifest_digest": record["task_manifest_digest"],
        "task_spec": spec["task_spec"],
        "qualification_input_artifact": record["qualification_input_artifact"],
        "repository": spec["provenance"]["repository"],
        "base_sha": spec["provenance"]["base_sha"],
        "checks": spec["checks"],
        "findings": spec["findings"],
        "evidence_refs": [evidence],
        "adjudicates": record["review_records"] if stage == "adjudicator" else [],
    }
    output = {"verdict": verdict, "checks": spec["checks"], "evidence_refs": [evidence]}
    receipt = {
        "schema_version": 1,
        "qualification_mode": "agent",
        "stage": stage,
        "task_id": record["task_id"],
        "task_manifest_digest": record["task_manifest_digest"],
        "qualification_input_artifact": record["qualification_input_artifact"],
        "invocation_id": str(uuid4()),
        "context_id": context_id or str(uuid4()),
        "provider": "fixture",
        "model": "synthetic-never-called",
        "provider_request_id": str(uuid4()),
        "prompt_digest": evidence,
        "config_digest": evidence,
        "input_digest": put(store, context),
        "output_digest": put(store, output),
        "started_at": "2026-09-28T12:00:00Z",
        "completed_at": "2026-09-28T12:00:01Z",
        "input_tokens": 100,
        "output_tokens": 10,
    }
    return put(store, receipt)


def validate(records):
    store, record, _ = records
    return validate_qualification(
        store,
        put(store, record),
        task_id=record["task_id"],
        task_manifest_digest=record["task_manifest_digest"],
    )


def replace_spec(records):
    store, record, spec = records
    record["qualification_input_artifact"] = put(store, spec)
    old_contexts = [get(store, ref)["context_id"] for ref in record["review_records"]]
    record["review_records"] = [
        make_review(store, record, spec, stage, context_id=old_contexts[index])
        for index, stage in enumerate(("qualifier_a", "qualifier_b"))
    ]


def test_complete_synthetic_records_admit_only_metadata(records):
    result = validate(records).model_dump()
    assert result == {
        "admitted": True,
        "qualification_mode": "agent",
        "task_id": "synthetic-task",
        "qualification_evidence_sha256": put(records[0], records[1]),
    }
    assert "behavior_nodes" not in json.dumps(result)
    assert "VALUE = 2" not in json.dumps(result)


@pytest.mark.parametrize("check", ["rights", "risk", "runtime", "leakage", "family", "oracle"])
@pytest.mark.parametrize("status", ["PENDING", "FAIL"])
def test_pending_or_failed_gate_cannot_be_overridden(records, check, status):
    records[2]["checks"][check] = status
    replace_spec(records)
    with pytest.raises(QualificationFailure, match="eligibility"):
        validate(records)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "stale_image",
        "false_pass",
        "early_exit",
        "stdout_only",
        "skip",
        "xfail",
        "collection",
        "missing_phase",
        "wrong_snapshot",
        "wrong_command",
        "regression_failure",
        "reused_nonce",
    ],
)
def test_execution_records_fail_closed(records, mutation):
    store, _, spec = records
    if mutation == "missing":
        spec["executions"].pop()
    elif mutation == "duplicate":
        spec["executions"][-1] = spec["executions"][-2]
    else:
        index = 3 if mutation == "regression_failure" else 0
        entry = spec["executions"][index]
        receipt = get(store, entry["receipt_artifact"])
        report = receipt["verification_report"]
        if mutation == "stale_image":
            receipt["image"] = "sha256:" + "0" * 64
        elif mutation == "false_pass":
            receipt["exit_code"] = report["exit_code"] = 0
            report["phases"][1]["outcome"] = "passed"
        elif mutation == "early_exit":
            report["session_finished"] = False
        elif mutation == "stdout_only":
            receipt["verification_report"] = None
            receipt["stdout"] = "1 failed then fixed and 1 passed"
        elif mutation == "skip":
            report["phases"][1]["outcome"] = "skipped"
        elif mutation == "xfail":
            report["phases"][1]["wasxfail"] = True
        elif mutation == "collection":
            report["collection_errors"] = ["broken import"]
        elif mutation == "missing_phase":
            report["phases"].pop()
        elif mutation == "wrong_snapshot":
            receipt["snapshot_digest"] = "f" * 64
        elif mutation == "wrong_command":
            receipt["argv"] = ["python", "-c", "print('passed')"]
        elif mutation == "regression_failure":
            receipt["exit_code"] = report["exit_code"] = 1
            report["phases"][1]["outcome"] = "failed"
        elif mutation == "reused_nonce":
            previous = get(store, spec["executions"][1]["receipt_artifact"])
            receipt["verification_binding"]["nonce"] = previous["verification_binding"]["nonce"]
            report["binding"]["nonce"] = previous["verification_binding"]["nonce"]
        entry["receipt_artifact"] = put(store, receipt)
    replace_spec(records)
    with pytest.raises(QualificationFailure):
        validate(records)


@pytest.mark.parametrize("field", ["context_id", "invocation_id", "provider_request_id"])
def test_reused_agent_context_or_operation_rejected(records, field):
    store, record, _ = records
    first = get(store, record["review_records"][0])
    second = get(store, record["review_records"][1])
    second[field] = first[field]
    record["review_records"][1] = put(store, second)
    with pytest.raises(QualificationFailure, match="independently"):
        validate(records)


@pytest.mark.parametrize(
    "mutation",
    [
        "role",
        "time",
        "model_missing",
        "input_missing",
        "peer_visible",
        "solution_in_context",
        "stale_input",
        "wrong_task",
        "missing_output",
    ],
)
def test_agent_receipt_binding_and_context_rejections(records, mutation):
    store, record, _ = records
    receipt = get(store, record["review_records"][0])
    if mutation == "role":
        receipt["stage"] = "qualifier_b"
    elif mutation == "time":
        receipt["completed_at"] = receipt["started_at"]
    elif mutation == "model_missing":
        receipt.pop("model")
    elif mutation == "input_missing":
        receipt["input_digest"] = "a" * 64
    elif mutation in {"peer_visible", "solution_in_context"}:
        context = get(store, receipt["input_digest"])
        if mutation == "peer_visible":
            context["adjudicates"] = record["review_records"]
        else:
            context["reference_solution"] = "VALUE = 2"
        receipt["input_digest"] = put(store, context)
    elif mutation == "stale_input":
        receipt["qualification_input_artifact"] = "a" * 64
    elif mutation == "wrong_task":
        receipt["task_id"] = "another-task"
    elif mutation == "missing_output":
        receipt["output_digest"] = "a" * 64
    record["review_records"][0] = put(store, receipt)
    with pytest.raises(QualificationFailure):
        validate(records)


@pytest.mark.parametrize("verdict", ["ADMIT", "REJECT", "UNRESOLVED"])
def test_disagreement_requires_third_distinct_adjudicator(records, verdict):
    store, record, spec = records
    record["review_records"][1] = make_review(store, record, spec, "qualifier_b", "REJECT")
    with pytest.raises(QualificationFailure, match="adjudication"):
        validate(records)
    record["adjudication_ref"] = make_review(store, record, spec, "adjudicator", verdict)
    if verdict == "ADMIT":
        assert validate(records).admitted
    else:
        with pytest.raises(QualificationFailure, match="rejected or unresolved"):
            validate(records)


def test_rejecting_qualifiers_do_not_admit(records):
    store, record, spec = records
    record["review_records"] = [
        make_review(store, record, spec, stage, "REJECT")
        for stage in ("qualifier_a", "qualifier_b")
    ]
    with pytest.raises(QualificationFailure, match="rejected or unresolved"):
        validate(records)


@pytest.mark.parametrize(
    "mutation",
    [
        "license_base",
        "issue_repo",
        "rights_missing",
        "source_changed",
        "oracle_changed",
        "nodes_duplicate",
        "risk",
        "license_unsupported",
    ],
)
def test_provenance_and_snapshot_fail_closed(records, mutation):
    store, _, spec = records
    if mutation == "license_base":
        spec["provenance"]["license_url"] = "https://github.com/fixture/repo/blob/main/LICENSE"
    elif mutation == "issue_repo":
        spec["provenance"]["issue_url"] = "https://github.com/other/repo/issues/1"
    elif mutation == "rights_missing":
        spec["provenance"]["usage_authorization_artifact"] = "f" * 64
    elif mutation == "source_changed":
        spec["provenance"]["source_snapshot_artifact"] = put(store, {"app.py": "VALUE = 999"})
    elif mutation == "oracle_changed":
        spec["oracle_artifact"] = put(store, {"tests/test_behavior.py": "assert True"})
    elif mutation == "nodes_duplicate":
        spec["behavior_nodes"] *= 2
    elif mutation == "risk":
        spec["risk_tier"] = 2
    elif mutation == "license_unsupported":
        spec["provenance"]["license_id"] = "UNKNOWN"
    replace_spec(records)
    with pytest.raises(QualificationFailure):
        validate(records)


def test_artifact_integrity_and_task_binding(records):
    store, record, _ = records
    digest = put(store, record)
    with pytest.raises(QualificationFailure, match="different task"):
        validate_qualification(
            store, digest, task_id="wrong", task_manifest_digest=record["task_manifest_digest"]
        )
    path = store.root / digest[:2] / digest
    path.write_bytes(b"{}")
    with pytest.raises(QualificationFailure):
        validate_qualification(
            store,
            digest,
            task_id=record["task_id"],
            task_manifest_digest=record["task_manifest_digest"],
        )


def test_task_digest_excludes_only_recursive_artifact():
    task = {"id": "one", "qualification_artifact": "a", "reviewers": ["agent-a", "agent-b"]}
    changed = {**task, "qualification_artifact": "b"}
    assert qualification_task_digest(task) == qualification_task_digest(changed)
    assert qualification_task_digest(task) != qualification_task_digest({**task, "reviewers": []})


def test_schema_is_strict_and_current_catalog_is_not_a_qualification():
    for contract in (QualificationRecord, QualificationInput, ReviewContext, AgentReview):
        assert contract.model_json_schema()["additionalProperties"] is False
    catalog = Path("evals/candidates/swebench-verified-36.json")
    with pytest.raises(ValueError):
        QualificationRecord.model_validate_json(catalog.read_text(encoding="utf-8"))


def task_document(records):
    store, record, spec = records
    provenance = spec["provenance"]
    return {
        "id": record["task_id"],
        "qualification_artifact": "0" * 64,
        "reviewers": [get(store, ref)["context_id"] for ref in record["review_records"]],
        "repository_url": f"https://github.com/{provenance['repository']}",
        "base_sha": provenance["base_sha"],
        "issue_url": provenance["issue_url"],
        "license_id": provenance["license_id"],
        "snapshot_artifact": provenance["source_snapshot_artifact"],
        "oracle_artifact": spec["oracle_artifact"],
        "image": spec["image"],
        "reference_snapshot_artifact": spec["reference_snapshot_artifact"],
        "reference_patch_artifact": spec["reference_patch_artifact"],
        "family": spec["family"],
        "split": spec["split"],
        "acceptance_commands": [spec["acceptance_command"]],
        "regression_commands": [spec["regression_command"]],
        "item": spec["task_spec"],
    }


def bind_document(records, document):
    _, record, spec = records
    record["task_manifest_digest"] = spec["task_manifest_digest"] = qualification_task_digest(
        document
    )
    replace_spec(records)


@pytest.mark.parametrize(
    "field",
    [
        None,
        "repository_url",
        "base_sha",
        "issue_url",
        "license_id",
        "snapshot_artifact",
        "oracle_artifact",
        "image",
        "family",
        "split",
        "reference_snapshot_artifact",
        "reference_patch_artifact",
        "acceptance_commands",
        "regression_commands",
        "item",
    ],
)
def test_current_manifest_facts_must_match_even_if_digest_rebound(records, field):
    store, record, _ = records
    document = task_document(records)
    if field:
        document[field] = {} if field == "item" else "mismatched"
    bind_document(records, document)
    if field is None:
        assert validate_qualification(
            store,
            put(store, record),
            task_id=record["task_id"],
            task_manifest_digest=record["task_manifest_digest"],
            task_document=document,
        ).admitted
    else:
        with pytest.raises(QualificationFailure, match="facts differ"):
            validate_qualification(
                store,
                put(store, record),
                task_id=record["task_id"],
                task_manifest_digest=record["task_manifest_digest"],
                task_document=document,
            )


def test_adjudicator_cannot_reuse_qualifier_context(records):
    store, record, spec = records
    record["review_records"][1] = make_review(store, record, spec, "qualifier_b", "REJECT")
    adjudicator_ref = make_review(store, record, spec, "adjudicator")
    adjudicator = get(store, adjudicator_ref)
    adjudicator["context_id"] = get(store, record["review_records"][0])["context_id"]
    record["adjudication_ref"] = put(store, adjudicator)
    with pytest.raises(QualificationFailure, match="independently"):
        validate(records)


def test_manifest_reviewer_labels_cannot_replace_context_ids(records):
    store, record, _ = records
    document = task_document(records)
    document["reviewers"] = ["invented-agent-a", "invented-agent-b"]
    bind_document(records, document)
    with pytest.raises(QualificationFailure, match="reviewer identities"):
        validate_qualification(
            store,
            put(store, record),
            task_id=record["task_id"],
            task_manifest_digest=record["task_manifest_digest"],
            task_document=document,
        )


@pytest.mark.parametrize("field", ["task_spec", "findings"])
def test_review_receipt_cannot_change_sanitized_facts(records, field):
    store, record, _ = records
    receipt = get(store, record["review_records"][0])
    context = get(store, receipt["input_digest"])
    if field == "task_spec":
        context[field]["description"] = "Different task, cherry-picked for easy acceptance"
    else:
        context[field][0]["summary"] = "An invented stronger finding"
    receipt["input_digest"] = put(store, context)
    record["review_records"][0] = put(store, receipt)
    with pytest.raises(QualificationFailure, match="binding mismatch"):
        validate(records)


def historical_task(records):
    """Normalize defaults before qualification hashing; never creates real qualification."""
    store, record, _ = records
    document = {
        **task_document(records),
        "qualification_mode": "independent-agents-v1",
    }
    normalized = HistoricalTask.model_validate(document).model_dump(mode="json")
    bind_document(records, normalized)
    normalized["qualification_artifact"] = put(store, record)
    return HistoricalTask.model_validate(normalized)


def export_paths(tmp_path_factory):
    # The records fixture's temporary directory is itself protected artifact storage.
    root = tmp_path_factory.mktemp("qualification-public-outputs")
    return root / "tasks.jsonl", root / "validation.json"


def write_tasks(path, *tasks):
    path.write_text(
        "\n".join(task.model_dump_json(exclude_defaults=True) for task in tasks) + "\n",
        encoding="utf-8",
    )


def qualification_cli(store, manifest, output):
    return evaluation_main(
        [
            "inspect-legacy-qualification",
            "--manifest",
            str(manifest),
            "--artifacts",
            str(store.root),
            "--output",
            str(output),
        ]
    )


def test_legacy_historical_task_roundtrip_and_inspection_never_authorize_export(
    records, tmp_path_factory
):
    store, record, spec = records
    task = historical_task(records)
    manifest, output = export_paths(tmp_path_factory)
    write_tasks(manifest, task)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    assert "schema_version" not in raw
    assert "budget" not in raw
    (reloaded,) = load_manifest(manifest)
    assert reloaded == task
    assert (
        qualification_task_digest(reloaded.model_dump(mode="json"))
        == record["task_manifest_digest"]
    )
    reloaded.inspect_legacy_qualification(store)
    with pytest.raises(ValueError, match="independent-agents-v2"):
        reloaded.worker_input(store)
    prohibited = [
        spec["oracle_artifact"],
        spec["reference_snapshot_artifact"],
        spec["reference_patch_artifact"],
        task.qualification_artifact,
        record["qualification_input_artifact"],
        *record["review_records"],
        *spec["behavior_nodes"],
        *spec["regression_nodes"],
        "VALUE = 2",
        "verification_report",
        "tests/test_behavior.py",
        "tests/test_regression.py",
        *task.reviewers,
    ]
    assert qualification_cli(store, manifest, output) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["qualification_verified"] is False
    assert result["execution_authorized"] is False
    assert result["historical_evidence_inspected"] is True
    assert result["qualification_mode"] == "independent-agents-v1"
    assert result["tasks"] == 1
    assert all(secret not in json.dumps(result) for secret in prohibited)


@pytest.mark.parametrize("mutation", ["budget", "item", "reviewers", "legacy", "reference_missing"])
def test_qualified_historical_task_mismatch_and_legacy_fail_before_export(
    records, tmp_path_factory, mutation
):
    store, _, _ = records
    document = historical_task(records).model_dump(mode="json")
    if mutation == "budget":
        document["budget"]["model_microdollars"] += 1
    elif mutation == "item":
        document["item"]["description"] = "An unreviewed revised task"
    elif mutation == "reviewers":
        document["reviewers"].reverse()
    elif mutation == "legacy":
        document["qualification_mode"] = "unverified"
    else:
        document["reference_snapshot_artifact"] = None
    changed = HistoricalTask.model_validate(document)
    with pytest.raises(ValueError):
        changed.inspect_legacy_qualification(store)
    with pytest.raises(ValueError):
        changed.worker_input(store)
    manifest, output = export_paths(tmp_path_factory)
    write_tasks(manifest, changed)
    with pytest.raises(SystemExit) as failure:
        qualification_cli(store, manifest, output)
    assert failure.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("existing_output", [False, True])
def test_qualification_cli_checks_entire_manifest_before_any_output(
    records, tmp_path_factory, existing_output
):
    store, _, _ = records
    valid = historical_task(records)
    invalid = valid.model_copy(update={"id": "unqualified-second-task"})
    manifest, output = export_paths(tmp_path_factory)
    write_tasks(manifest, valid, invalid)
    previous = b"Previous output must survive an unsuccessful replacement\n"
    if existing_output:
        output.write_bytes(previous)
    with pytest.raises(SystemExit):
        qualification_cli(store, manifest, output)
    if existing_output:
        assert output.read_bytes() == previous
    else:
        assert not output.exists()


@pytest.mark.parametrize("location", ["protected_root", "artifact", "manifest"])
def test_qualification_cli_cannot_overwrite_protected_evidence_or_manifest(
    records, tmp_path_factory, location
):
    store, _, _ = records
    task = historical_task(records)
    manifest, _ = export_paths(tmp_path_factory)
    write_tasks(manifest, task)
    if location == "protected_root":
        output = store.root / "report.json"
    elif location == "artifact":
        output = store.root / task.qualification_artifact[:2] / task.qualification_artifact
    else:
        output = manifest
    previous = output.read_bytes() if output.exists() else None
    with pytest.raises(SystemExit):
        qualification_cli(store, manifest, output)
    if previous is not None:
        assert output.read_bytes() == previous
    else:
        assert not output.exists()


@pytest.mark.parametrize("location", ["same", "nested", "parent"])
async def test_scoring_rejects_overlapping_protected_and_result_stores(
    records, location, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Overlapping stores must fail before qualification reads")

    # Reject invalid storage before reading qualification or protected payloads.
    monkeypatch.setattr(
        HistoricalTask,
        "validate_qualification",
        forbidden,
    )
    store, _, _ = records
    task = historical_task(records)
    target = {"same": store.root, "nested": store.root / "results", "parent": store.root.parent}[
        location
    ]
    output = ArtifactStore(target)
    with pytest.raises(ValueError, match="disjoint"):
        await score_candidate(task, {"app.py": "VALUE = 2\n"}, store, output)


@pytest.mark.integration
async def test_actual_three_repeat_oracle_receipts_with_synthetic_agent_records(records):
    """Real Docker oracle executions; agent/rights records remain unit-test fabrications."""
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    store, _, spec = records
    runner = DockerRunner(image)
    await runner.preflight()
    spec["image"] = image
    source = {"app.py": "VALUE = 1\n"}
    oracle = {
        "tests/test_behavior.py": "from app import VALUE\ndef test_value(): assert VALUE == 2\n",
        "tests/test_regression.py": (
            "from app import VALUE\ndef test_existing(): assert VALUE > 0\n"
        ),
    }
    baseline = {**source, **oracle}
    reference = {**baseline, "app.py": "VALUE = 2\n"}
    spec["provenance"]["source_snapshot_artifact"] = put(store, source)
    spec["oracle_artifact"] = put(store, oracle)
    spec["baseline_snapshot_artifact"] = put(store, baseline)
    spec["reference_snapshot_artifact"] = put(store, reference)
    for execution in spec["executions"]:
        command = CommandProfile.model_validate(spec[execution["suite"] + "_command"])
        files = baseline if execution["variant"] == "baseline" else reference
        summary = await verify(
            files,
            (command,),
            runner,
            store,
            timeout=20,
            workflow_id=f"qualification-unit-{uuid4().hex}",
        )
        execution["receipt_artifact"] = summary["commands"][0]["artifact_digest"]
    replace_spec(records)
    assert validate(records).admitted
