"""Authored toy imports and structural subjects only; no runtime or model evidence claims."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.evaluation.qualification import (
    QualificationInput,
    qualification_task_digest,
)
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    _read,
    parse_task,
    prepare_qualification,
)
from agentic_delivery.evaluation.qualification_v2 import (
    CalibrationReviewSubject,
    subject_manifest_digest,
)
from agentic_delivery.evaluation.synthetic_examples import (
    AuthoredFile,
    build_synthetic_examples,
    files_dict,
)
from agentic_delivery.evaluation.synthetic_import import (
    import_synthetic_example,
    materialize_synthetic_subject,
)
from agentic_delivery.storage.artifacts import ArtifactStore

RIGHTS = (
    "Newly authored project-owned calibration fixture for explicitly authorized internal model "
    "processing and synthetic validation only. This is no grant to redistribute any project "
    "or third-party source and does not establish historical benchmark rights.\n"
)
ROLES = ("rights", "risk", "runtime", "leakage", "family", "oracle")
NOW = datetime(2026, 9, 28, tzinfo=UTC)
IMAGE = "sha256:" + "e" * 64


@pytest.fixture
def authored(tmp_path):
    artifacts = ArtifactStore(tmp_path / "protected")
    options = dict(
        artifacts=artifacts,
        construction_revision="a" * 40,  # Clearly synthetic test construction revision.
        image=IMAGE,
        budget=Budget(),
        issuer="test-controller",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        reviewers=("reserved-context-a", "reserved-context-b"),
    )
    examples = build_synthetic_examples(repository="fixture/repo", rights_text=RIGHTS)
    return examples, options


def _put(artifacts, document):
    return artifacts.put(json.dumps(document, sort_keys=True).encode())


def _snapshot(artifacts):
    return {
        str(p.relative_to(artifacts.root)): p.read_bytes()
        for p in artifacts.root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("index", range(5))
def test_all_authored_examples_import_and_prepare_without_execution(authored, tmp_path, index):
    examples, options = authored
    example, artifacts = examples[index], options["artifacts"]
    imported = import_synthetic_example(example, **options)
    assert imported == import_synthetic_example(example, **options)
    assert _read(artifacts, imported.authoring_artifact) == example.model_dump(mode="json")
    task = parse_task(_read(artifacts, imported.task_artifact))
    assert task.authoring_artifact == imported.authoring_artifact
    assert task.item == example.safe_task
    assert task.reviewers == options["reviewers"]
    assert task.family == "authored-label-normalization" and task.split == "development"
    for secret in ("reference_files", '"expected"', '"category"', "known_admit", "known_reject"):
        assert secret not in imported.model_dump_json()
        assert secret not in task.model_dump_json()
    authorization = _read(artifacts, imported.authorization_artifact)
    assert authorization["task_manifest_digest"] == qualification_task_digest(
        task.model_dump(mode="json")
    )
    worker, output = tmp_path / "worker", tmp_path / "output"
    worker.mkdir()
    output.mkdir()
    settings = Settings(
        repositories=(
            RepositoryConfig(
                id="fixture/repo",
                github_owner="fixture",
                github_name="repo",
                sandbox_image=IMAGE,
                model_data_authorized=True,
                commands=(example.acceptance_command, example.regression_command),
            ),
        )
    )
    policy = PreparationPolicy(
        schema_version=1,
        policy_version="mvp-1",
        authorized_issuers=("test-controller",),
        approved_authorization_artifacts=(imported.authorization_artifact,),
    )
    prepared = prepare_qualification(
        imported.preparation,
        settings=settings,
        policy=policy,
        protected_artifacts=artifacts,
        output_root=output,
        worker_root=worker,
        now=NOW,
    )
    assert not prepared.admitted and not prepared.execution_authorized
    with pytest.raises(ValueError):
        task.worker_input(artifacts)


@pytest.mark.parametrize(
    "defect",
    [
        "revision",
        "image",
        "issuer",
        "time",
        "naive",
        "contexts",
        "patch",
        "reference",
        "collision",
        "rights",
        "duplicate",
        "risk",
        "node",
        "scope",
        "size",
    ],
)
def test_invalid_import_fails_before_any_artifact_write(authored, defect):
    examples, options = authored
    example = examples[0]
    artifacts = options["artifacts"]
    if defect == "revision":
        options["construction_revision"] = "f" * 64
    elif defect == "image":
        options["image"] = "latest"
    elif defect == "issuer":
        options["issuer"] = ""
    elif defect == "time":
        options["expires_at"] = options["issued_at"]
    elif defect == "naive":
        options["issued_at"] = datetime(2026, 9, 28)
    elif defect == "contexts":
        options["reviewers"] = ("same", "same")
    elif defect == "patch":
        example = example.model_copy(update={"reference_patch": "invalid patch\n"})
    elif defect == "reference":
        example = example.model_copy(update={"reference_files": example.source_files})
    elif defect == "collision":
        example = example.model_copy(update={"oracle_files": example.source_files})
    elif defect == "rights":
        example = example.model_copy(
            update={
                "source_files": tuple(
                    f for f in example.source_files if f.path != "FIXTURE_RIGHTS.txt"
                )
            }
        )
    elif defect == "duplicate":
        example = example.model_copy(
            update={"source_files": (*example.source_files, example.source_files[0])}
        )
    elif defect == "risk":
        example = example.model_copy(update={"safe_task": examples[3].subject.task_spec})
    elif defect == "node":
        example = example.model_copy(update={"behavior_nodes": ("tests/other.py::test_other",)})
    elif defect == "scope":
        subject = example.subject.model_copy(
            update={
                "task_spec": example.subject.task_spec.model_copy(
                    update={"repository": "other/repo"}
                )
            }
        )
        example = example.model_copy(update={"subject": subject})
    else:
        example = example.model_copy(
            update={
                "source_files": (
                    *example.source_files,
                    AuthoredFile(path="large.txt", text="x" * (256 * 1024 + 1)),
                )
            }
        )
    with pytest.raises(ValueError):
        import_synthetic_example(example, **options)
    assert _snapshot(artifacts) == {}


def structural_anchor(example, imported, artifacts):
    """Artifact-only test input; never claims trusted execution or twelve real runs."""
    task = parse_task(_read(artifacts, imported.task_artifact))
    document_ref = artifacts.put(b"Synthetic structural fixture, not trusted runtime evidence.")
    receipt_ref = artifacts.put(b"No actual operation receipt: helper binds metadata only.")
    return QualificationInput.model_validate(
        dict(
            schema_version=1,
            task_id=task.id,
            task_manifest_digest=qualification_task_digest(task.model_dump(mode="json")),
            task_spec=task.item.model_dump(mode="json"),
            provenance=_read(artifacts, imported.preparation.provenance_artifact),
            checks={role: "PASS" for role in ROLES},
            check_evidence={role: document_ref for role in ROLES},
            findings=[
                dict(
                    check=role,
                    status="PASS",
                    summary="Synthetic structural fixture only",
                    evidence_refs=[document_ref],
                )
                for role in ROLES
            ],
            risk_tier=task.item.risk_tier,
            family=task.family,
            split="development",
            image=task.image,
            baseline_snapshot_artifact=_put(
                artifacts, {**files_dict(example.source_files), **files_dict(example.oracle_files)}
            ),
            reference_snapshot_artifact=task.reference_snapshot_artifact,
            reference_patch_artifact=task.reference_patch_artifact,
            oracle_artifact=task.oracle_artifact,
            acceptance_command=example.acceptance_command.model_dump(mode="json"),
            regression_command=example.regression_command.model_dump(mode="json"),
            behavior_nodes=example.behavior_nodes,
            regression_nodes=example.regression_nodes,
            executions=[
                dict(variant=variant, suite=suite, repetition=n, receipt_artifact=receipt_ref)
                for variant in ("baseline", "reference")
                for suite in ("acceptance", "regression")
                for n in (1, 2, 3)
            ],
        )
    )


def test_subject_materialization_excludes_expected_decisions_and_reference(authored):
    examples, options = authored
    example, artifacts = examples[3], options["artifacts"]
    imported = import_synthetic_example(example, **options)
    anchor = structural_anchor(example, imported, artifacts)
    anchor_ref = _put(artifacts, anchor.model_dump(mode="json"))
    ref = materialize_synthetic_subject(imported, anchor_ref, artifacts=artifacts)
    subject = CalibrationReviewSubject.model_validate(_read(artifacts, ref))
    assert subject.task_manifest_digest == subject_manifest_digest(subject)
    assert subject.task_spec == example.subject.task_spec
    assert subject.task_spec.risk_tier == 3 and anchor.risk_tier == 1
    assert subject.execution_anchor_artifact == anchor_ref
    assert subject.task_id == example.subject.task_spec.id
    for authored_document in example.subject.documents:
        assert (
            artifacts.get(subject.check_evidence[authored_document.role]).decode()
            == authored_document.text
        )
    text = subject.model_dump_json() + "".join(
        artifacts.get(r).decode() for r in subject.check_evidence.values()
    )
    for denied in ('"expected"', '"category"', "reference_files", "return text.strip", '"REJECT"'):
        assert denied not in text


@pytest.mark.parametrize(
    "defect", ["authoring", "task", "oracle", "provenance", "nodes", "baseline"]
)
def test_subject_grafts_fail_before_new_writes(authored, defect):
    examples, options = authored
    example, artifacts = examples[0], options["artifacts"]
    imported = import_synthetic_example(example, **options)
    anchor = structural_anchor(example, imported, artifacts)
    if defect == "authoring":
        changed = example.model_copy(update={"subject": examples[1].subject})
        imported = imported.model_copy(
            update={"authoring_artifact": _put(artifacts, changed.model_dump(mode="json"))}
        )
    elif defect == "task":
        anchor = anchor.model_copy(update={"task_id": "other"})
    elif defect == "oracle":
        anchor = anchor.model_copy(update={"oracle_artifact": "f" * 64})
    elif defect == "provenance":
        anchor = anchor.model_copy(
            update={
                "provenance": anchor.provenance.model_copy(
                    update={"construction_revision": "f" * 40}
                )
            }
        )
    elif defect == "nodes":
        anchor = anchor.model_copy(update={"behavior_nodes": ("tests/other.py::test_other",)})
    else:
        anchor = anchor.model_copy(
            update={"baseline_snapshot_artifact": anchor.reference_snapshot_artifact}
        )
    ref = _put(artifacts, anchor.model_dump(mode="json"))
    before = _snapshot(artifacts)
    with pytest.raises(ValueError):
        materialize_synthetic_subject(imported, ref, artifacts=artifacts)
    assert _snapshot(artifacts) == before
