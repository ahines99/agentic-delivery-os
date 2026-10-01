"""Synthetic acquisition records only; no actual historical payloads or rights claims."""

import hashlib
import json
from datetime import timedelta

import pytest
from test_qualification_preparation import NOW, SOURCE, put, synthetic  # noqa: F401

from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.historical_import import (
    HistoricalAcquisitionEvidence,
    HistoricalImportFailure,
    HistoricalImportRequest,
    import_historical_task,
)
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def acquired(synthetic):  # noqa: F811
    source = {
        **SOURCE,
        "pyproject.toml": "[tool.example]\nvalue = 1\n",
        "docs/original.txt": "Original UTF-8 café\r\nSecond unchanged line\r\n",
    }
    preparation, options, task = synthetic(
        source=source, task_changes={"qualification_mode": "independent-agents-v2"}
    )
    store = options["protected_artifacts"]
    provenance = json.loads(store.get(preparation.provenance_artifact))
    reference = json.loads(store.get(preparation.reference_provenance_artifact))
    document = {
        "schema_version": 1,
        "source_scope": "FULL_REPOSITORY",
        "repository": provenance["repository"],
        "base_sha": task["base_sha"],
        "source_task_id": provenance["source_task_id"],
        "source_url": provenance["source_url"],
        "source_revision": provenance["source_revision"],
        "task_manifest_digest": qualification_task_digest(task),
        "source_snapshot_artifact": task["snapshot_artifact"],
        "source_inventory": [
            {
                "path": path,
                "kind": "regular-file",
                "byte_length": len(text.encode()),
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
            for path, text in source.items()
        ],
        "issue_url": task["issue_url"],
        "issue_created_at": (NOW - timedelta(days=4)).isoformat(),
        "requirements_artifact": store.put(
            b"Explicit synthetic pre-solution requirements fixture; this is not a historical issue."
        ),
        "requirements_as_of": (NOW - timedelta(days=3)).isoformat(),
        "task_spec_digest": digest_json(task["item"]),
        "accepted_commit": reference["accepted_commit"],
        "accepted_commit_url": reference["accepted_commit_url"],
        "accepted_at": (NOW - timedelta(days=2)).isoformat(),
        "acquired_at": (NOW - timedelta(days=1)).isoformat(),
        "oracle_artifact": task["oracle_artifact"],
        "reference_snapshot_artifact": task["reference_snapshot_artifact"],
        "reference_patch_artifact": task["reference_patch_artifact"],
    }
    request = HistoricalImportRequest(
        schema_version=1, preparation=preparation, acquisition_artifact=put(store, document)
    )
    return request, options, task, document


def _snapshot(store):
    return {
        str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()
    }


def test_offline_import_preserves_exact_source_bytes_without_admission(acquired):
    request, options, task, _ = acquired
    store = options["protected_artifacts"]
    before = _snapshot(store)
    imported = import_historical_task(request, **options)
    assert imported.status == "IMPORTED_NOT_QUALIFIED"
    assert not imported.admitted and not imported.execution_authorized
    assert imported.task_artifact == request.preparation.task_artifact
    assert imported.preparation == request.preparation
    after = _snapshot(store)
    assert all(after[path] == content for path, content in before.items())
    assert len(after) == len(before) + 2
    assert _snapshot(store) == after
    assert import_historical_task(request, **options) == imported
    assert _snapshot(store) == after
    serialized = imported.model_dump_json()
    for private_text in ("VALUE =", "test_value", "café", "pre-solution requirements"):
        assert private_text not in serialized
    with pytest.raises(ValueError):
        HistoricalTask.model_validate(task).worker_input(store)


@pytest.mark.parametrize(
    "defect",
    [
        "missing_path",
        "extra_path",
        "duplicate_path",
        "bad_path",
        "changed_byte",
        "changed_size",
        "symlink",
        "empty_inventory",
        "slice",
        "unknown_field",
        "repository",
        "base_sha",
        "source_task_id",
        "source_url",
        "source_revision",
        "task_manifest_digest",
        "task_spec_digest",
        "source_snapshot_artifact",
        "issue_url",
        "accepted_commit",
        "accepted_commit_url",
        "oracle_artifact",
        "reference_snapshot_artifact",
        "reference_patch_artifact",
        "future_acquisition",
        "late_requirements",
        "before_issue",
        "acquisition_before_acceptance",
        "naive_time",
        "requirements_reference",
        "requirements_empty",
        "requirements_binary",
        "requirements_large",
    ],
)
def test_inconsistent_acquisition_refuses_before_metadata_writes(acquired, defect):
    request, options, _, document = acquired
    store = options["protected_artifacts"]
    if defect == "missing_path":
        document["source_inventory"].pop()
    elif defect == "extra_path":
        document["source_inventory"].append(
            {**document["source_inventory"][0], "path": "extra.txt"}
        )
    elif defect == "duplicate_path":
        document["source_inventory"].append(document["source_inventory"][0])
    elif defect == "bad_path":
        document["source_inventory"][0]["path"] = "../app.py"
    elif defect == "changed_byte":
        document["source_inventory"][0]["content_sha256"] = "f" * 64
    elif defect == "changed_size":
        document["source_inventory"][0]["byte_length"] += 1
    elif defect == "symlink":
        document["source_inventory"][0]["kind"] = "symlink"
    elif defect == "empty_inventory":
        document["source_inventory"] = []
    elif defect == "slice":
        document["source_scope"] = "SUBDIRECTORY"
    elif defect == "unknown_field":
        document["excluded_paths"] = ["pyproject.toml"]
    elif defect == "future_acquisition":
        document["acquired_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif defect == "late_requirements":
        document["requirements_as_of"] = document["accepted_at"]
    elif defect == "before_issue":
        document["requirements_as_of"] = (NOW - timedelta(days=5)).isoformat()
    elif defect == "acquisition_before_acceptance":
        document["acquired_at"] = document["requirements_as_of"]
    elif defect == "naive_time":
        document["acquired_at"] = "2026-09-27T00:00:00"
    elif defect == "requirements_reference":
        document["requirements_artifact"] = document["reference_patch_artifact"]
    elif defect == "requirements_empty":
        document["requirements_artifact"] = store.put(b" \n")
    elif defect == "requirements_binary":
        document["requirements_artifact"] = store.put(b"\xff\xfe")
    elif defect == "requirements_large":
        document["requirements_artifact"] = store.put(b"x" * (32 * 1024 + 1))
    elif defect in {"base_sha", "source_revision", "accepted_commit"}:
        document[defect] = "f" * 40
    elif defect.endswith("digest") or defect.endswith("artifact"):
        document[defect] = "f" * 64
    else:
        document[defect] = "different"
    request = request.model_copy(update={"acquisition_artifact": put(store, document)})
    before = _snapshot(store)
    with pytest.raises(HistoricalImportFailure) as error:
        import_historical_task(request, **options)
    assert (
        str(error.value)
        == "Historical import refused; inspect protected acquisition evidence privately"
    )
    assert error.value.__cause__ is None
    assert _snapshot(store) == before


@pytest.mark.parametrize("defect", ["revoked", "expired", "disabled", "scope", "command", "legacy"])
def test_existing_preparation_authority_cannot_be_bypassed(acquired, defect):
    request, options, task, _ = acquired
    store = options["protected_artifacts"]
    if defect == "revoked":
        options["policy"] = options["policy"].model_copy(
            update={"approved_authorization_artifacts": ("f" * 64,)}
        )
    elif defect == "expired":
        options["now"] += timedelta(days=2)
    elif defect == "disabled":
        options["settings"] = options["settings"].model_copy(update={"admissions_enabled": False})
    elif defect == "scope":
        options["worker_root"] = store.root
    elif defect == "command":
        repo = options["settings"].repositories[0].model_copy(update={"commands": ()})
        options["settings"] = options["settings"].model_copy(update={"repositories": (repo,)})
    else:
        task["qualification_mode"] = "independent-agents-v1"
        preparation = request.preparation.model_copy(update={"task_artifact": put(store, task)})
        request = request.model_copy(update={"preparation": preparation})
    before = _snapshot(store)
    with pytest.raises(HistoricalImportFailure):
        import_historical_task(request, **options)
    assert _snapshot(store) == before


def test_contract_requires_inventory_not_completeness_flag(acquired):
    _, _, _, document = acquired
    del document["source_inventory"]
    document["complete"] = True
    with pytest.raises(ValueError):
        HistoricalAcquisitionEvidence.model_validate(document)
