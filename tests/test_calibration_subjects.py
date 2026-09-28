"""Truthful subject/anchor projections; unit receipts are synthetic, not runtime proof."""

import json
from types import SimpleNamespace

import pytest
from test_calibration import frozen as calibration_fixture
from test_qualification import put, records
from test_qualification_v2 import context_fixture, output_for

from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation.calibration import _load_spec
from agentic_delivery.evaluation.qualification import QualificationInput, validate_qualification
from agentic_delivery.evaluation.qualification_v2 import (
    ELIGIBILITY,
    CalibrationReviewSubject,
    EvidenceCitationV2,
    FrozenCalibrationEvidenceV2,
    ReviewContextV2,
    ReviewEvidenceFailure,
    assemble_review_context,
    resolve_reviews,
    subject_manifest_digest,
    validate_review_context,
    validate_review_output,
)
from agentic_delivery.evaluation.synthetic_types import SyntheticProvenance
from agentic_delivery.storage.store import digest_json

frozen = calibration_fixture


def subject_fixture(tmp_path, *, risk=3):
    artifacts, historical = context_fixture(tmp_path)
    spec = json.loads(artifacts.get(historical.evidence.qualification_input_artifact))
    original = spec["provenance"]
    spec["provenance"] = {
        "schema_version": 1,
        "kind": "project-owned-synthetic",
        "purpose": "SYNTHETIC_VALIDATION",
        "construction_revision": "a" * 40,
        "authoring_artifact": artifacts.put(
            b"Private aggregate: reference implementation and expected judgments."
        ),
        "repository": original["repository"],
        "source_snapshot_artifact": original["source_snapshot_artifact"],
        "license_id": "MIT",
        "license_evidence_artifact": original["license_evidence_artifact"],
        "usage_authorization_artifact": original["usage_authorization_artifact"],
        "rights_scope": "PROJECT_OWNED_FIXTURE_AND_INTERNAL_MODEL_PROCESSING",
    }
    anchor = QualificationInput.model_validate(spec)
    task = WorkItem.model_validate(
        {
            **anchor.task_spec.model_dump(mode="json"),
            "id": "inert-subject",
            "risk_tier": risk,
            "description": "Hypothetical request to change production authorization controls.",
            "ambiguities": ("The required approval scope has not been specified.",),
        }
    )
    subject = CalibrationReviewSubject(
        schema_version=1,
        kind="synthetic-calibration-review-subject",
        task_id="inert-subject",
        task_manifest_digest="0" * 64,
        execution_anchor_artifact=put(artifacts, spec),
        task_spec=task,
        check_evidence={
            role: artifacts.put(
                (
                    "Subject support for "
                    + role
                    + ": this document concerns only the hypothetical request; "
                    "execution applies to the separate safe anchor."
                ).encode()
            )
            for role in ELIGIBILITY
        },
    )
    subject = subject.model_copy(update={"task_manifest_digest": subject_manifest_digest(subject)})
    return artifacts, anchor, subject, historical.evidence.rubric_artifact


def assemble(artifacts, subject, rubric):
    return assemble_review_context(
        artifacts,
        put(artifacts, subject.model_dump(mode="json")),
        rubric_artifact=rubric,
        stage="qualifier_a",
        context_id="subject-context",
    )


def rebind(subject, **updates):
    changed = subject.model_copy(update=updates)
    return changed.model_copy(update={"task_manifest_digest": subject_manifest_digest(changed)})


def test_historical_context_serialization_remains_unchanged(tmp_path):
    artifacts, context = context_fixture(tmp_path)
    document = context.model_dump(mode="json")
    assert not isinstance(context.evidence, FrozenCalibrationEvidenceV2)
    assert (
        not {"kind", "purpose", "execution_scope", "subject_executed"} & document["evidence"].keys()
    )
    assert ReviewContextV2.model_validate(document).model_dump(mode="json") == document
    validate_review_context(context, artifacts)


@pytest.mark.parametrize("risk", [None, 0, 1, 2, 3])
def test_subject_risk_is_inert_and_execution_scope_remains_safe(tmp_path, risk):
    artifacts, anchor, subject, rubric = subject_fixture(tmp_path, risk=risk)
    context = assemble(artifacts, subject, rubric)
    evidence = context.evidence
    assert isinstance(evidence, FrozenCalibrationEvidenceV2)
    assert evidence.subject_executed is False
    assert evidence.purpose == "CALIBRATION_ONLY"
    assert evidence.task_spec == subject.task_spec
    assert evidence.task_spec.risk_tier == risk
    assert set(evidence.declared_checks.model_dump().values()) == {"PENDING"}
    assert evidence.execution_scope.task_spec == anchor.task_spec
    assert evidence.execution_scope.task_spec.risk_tier <= 1
    assert evidence.execution_scope.declared_checks == anchor.checks
    assert (
        evidence.execution_scope.qualification_input_artifact == subject.execution_anchor_artifact
    )
    assert len(set(evidence.execution_scope.runtime_operation_ids)) == 12
    assert evidence.provenance == anchor.provenance
    assert isinstance(evidence.provenance, SyntheticProvenance)
    assert context.task_manifest_digest == subject_manifest_digest(subject)
    validate_review_context(context, artifacts)
    assert ReviewContextV2.model_validate_json(context.model_dump_json()) == context
    serialized = context.model_dump_json()
    for withheld in (
        anchor.reference_patch_artifact,
        anchor.reference_snapshot_artifact,
        "expected_verdict",
        "expected_findings",
        "VALUE = 2",
    ):
        assert withheld not in serialized


@pytest.mark.parametrize("mutation", ["digest", "spec", "support", "anchor"])
def test_subject_digest_binds_every_review_input(tmp_path, mutation):
    artifacts, _, subject, rubric = subject_fixture(tmp_path)
    changes = {
        "digest": {"task_manifest_digest": "f" * 64},
        "spec": {"task_spec": subject.task_spec.model_copy(update={"title": "changed subject"})},
        "support": {
            "check_evidence": {**subject.check_evidence, "risk": artifacts.put(b"changed support")}
        },
        "anchor": {"execution_anchor_artifact": "f" * 64},
    }
    with pytest.raises(ReviewEvidenceFailure):
        assemble(artifacts, subject.model_copy(update=changes[mutation]), rubric)


@pytest.mark.parametrize(
    "mutation",
    [
        "historical",
        "validation",
        "test",
        "unsafe",
        "missing_receipt",
        "duplicate_operation",
        "nested_subject",
    ],
)
def test_anchor_must_be_safe_complete_synthetic_development(tmp_path, mutation):
    artifacts, anchor, subject, rubric = subject_fixture(tmp_path)
    document = anchor.model_dump(mode="json")
    if mutation == "historical":
        _, historical = context_fixture(tmp_path / "historical")
        document["provenance"] = historical.evidence.provenance.model_dump(mode="json")
    elif mutation in {"validation", "test"}:
        document["split"] = mutation
    elif mutation == "unsafe":
        document["risk_tier"] = document["task_spec"]["risk_tier"] = 3
    elif mutation == "missing_receipt":
        document["executions"][0]["receipt_artifact"] = "f" * 64
    elif mutation == "duplicate_operation":
        first, second = document["executions"][:2]
        receipt = json.loads(artifacts.get(second["receipt_artifact"]))
        receipt["workflow_id"] = json.loads(artifacts.get(first["receipt_artifact"]))["workflow_id"]
        second["receipt_artifact"] = put(artifacts, receipt)
    else:
        document = subject.model_dump(mode="json")
    changed = rebind(subject, execution_anchor_artifact=put(artifacts, document))
    with pytest.raises(ReviewEvidenceFailure):
        assemble(artifacts, changed, rubric)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_role",
        "extra_role",
        "aliased_roles",
        "reference",
        "anchor_document",
        "foreign_repository",
        "no_criteria",
    ],
)
def test_subject_evidence_is_complete_independent_and_has_no_reference_artifacts(
    tmp_path, mutation
):
    artifacts, anchor, subject, rubric = subject_fixture(tmp_path)
    updates = {}
    documents = dict(subject.check_evidence)
    if mutation == "missing_role":
        documents.pop("risk")
    elif mutation == "extra_role":
        documents["expected_verdict"] = artifacts.put(b"REJECT")
    elif mutation == "aliased_roles":
        documents["risk"] = documents["rights"]
    elif mutation == "reference":
        documents["risk"] = anchor.reference_patch_artifact
    elif mutation == "anchor_document":
        documents["risk"] = anchor.check_evidence["risk"]
    elif mutation == "foreign_repository":
        updates["task_spec"] = subject.task_spec.model_copy(
            update={"repository": "other/repository"}
        )
    else:
        updates["task_spec"] = subject.task_spec.model_copy(update={"acceptance_criteria": ()})
    updates["check_evidence"] = documents
    with pytest.raises(ReviewEvidenceFailure):
        assemble(artifacts, rebind(subject, **updates), rubric)


@pytest.mark.parametrize(
    "field", ["expected_verdict", "expected_findings", "reference_patch_artifact"]
)
def test_subject_contract_has_no_expected_answers_or_solution_fields(tmp_path, field):
    _, _, subject, _ = subject_fixture(tmp_path)
    with pytest.raises(ValueError):
        CalibrationReviewSubject.model_validate(
            {**subject.model_dump(mode="json"), field: "private"}
        )


def test_context_reconstruction_detects_scope_and_pending_check_tampering(tmp_path):
    artifacts, _, subject, rubric = subject_fixture(tmp_path)
    context = assemble(artifacts, subject, rubric)
    changed_evidence = context.evidence.model_copy(
        update={
            "declared_checks": context.evidence.declared_checks.model_copy(update={"risk": "PASS"})
        }
    )
    changed = context.model_copy(
        update={
            "evidence": changed_evidence,
            "evidence_digest": digest_json(changed_evidence.model_dump(mode="json")),
        }
    )
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_context(changed, artifacts)
    changed_evidence = context.evidence.model_copy(
        update={
            "execution_scope": context.evidence.execution_scope.model_copy(
                update={"task_id": "other-anchor"}
            )
        }
    )
    changed = context.model_copy(
        update={
            "evidence": changed_evidence,
            "evidence_digest": digest_json(changed_evidence.model_dump(mode="json")),
        }
    )
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_context(changed, artifacts)


def test_subject_output_cites_subject_facts_separately_from_safe_anchor(tmp_path):
    artifacts, _, subject, rubric = subject_fixture(tmp_path)
    context = assemble(artifacts, subject, rubric)
    output = output_for(context, statuses={"eligibility:risk": "FAIL"})
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_output(output, context)
    findings = tuple(
        f.model_copy(
            update={
                "citations": (
                    *f.citations,
                    EvidenceCitationV2(
                        artifact_digest=subject.check_evidence[
                            "oracle" if f.target_kind == "criterion" else f.target_id
                        ]
                    ),
                )
            }
        )
        for f in output.findings
    )
    validate_review_output(output.model_copy(update={"findings": findings}), context)


def test_subject_cannot_resolve_into_qualification_even_with_forged_pass_checks(tmp_path):
    artifacts, _, subject, rubric = subject_fixture(tmp_path)
    context = assemble(artifacts, subject, rubric)
    evidence = context.evidence.model_copy(
        update={
            "declared_checks": context.evidence.declared_checks.model_copy(
                update=dict.fromkeys(ELIGIBILITY, "PASS")
            )
        }
    )
    review = SimpleNamespace(context=context.model_copy(update={"evidence": evidence}))
    with pytest.raises(ReviewEvidenceFailure, match="Calibration-only"):
        resolve_reviews(review, review)


def test_synthetic_input_does_not_weaken_legacy_historical_admission(tmp_path):
    artifacts, record, specification = records.__wrapped__(tmp_path / "legacy")
    _, anchor, _, _ = subject_fixture(tmp_path / "synthetic")
    specification["provenance"] = {
        **anchor.provenance.model_dump(mode="json"),
        "source_snapshot_artifact": specification["provenance"]["source_snapshot_artifact"],
    }
    record["qualification_input_artifact"] = put(artifacts, specification)
    with pytest.raises(ValueError, match="historical provenance"):
        validate_qualification(
            artifacts,
            put(artifacts, record),
            task_id=record["task_id"],
            task_manifest_digest=record["task_manifest_digest"],
        )


def test_subject_artifact_cannot_parse_as_controller_qualification_input(tmp_path):
    _, _, subject, _ = subject_fixture(tmp_path)
    with pytest.raises(ValueError):
        QualificationInput.model_validate(subject.model_dump(mode="json"))


def test_erasing_calibration_discriminator_does_not_upgrade_context(tmp_path):
    artifacts, _, subject, rubric = subject_fixture(tmp_path)
    context = assemble(artifacts, subject, rubric)
    document = context.model_dump(mode="json")
    for field in ("kind", "purpose", "subject_executed", "execution_scope"):
        document["evidence"].pop(field)
    document["evidence_digest"] = digest_json(document["evidence"])
    downgraded = ReviewContextV2.model_validate(document)
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_context(downgraded, artifacts)


def test_existing_calibration_loader_reconstructs_subject_union_without_expected_leakage(
    frozen, tmp_path
):
    case = frozen()
    subject_artifacts, _, subject, _ = subject_fixture(tmp_path / "subject")
    # Copy only bounded local synthetic fixture artifacts into this isolated fixture store.
    for file in subject_artifacts.root.glob("*/*"):
        case["artifacts"].put(file.read_bytes())
    specification = case["spec"].model_dump(mode="json")
    contexts = []
    for index, fixture in enumerate(specification["fixtures"]):
        variation = rebind(subject, task_id="neutral-subject-" + str(index))
        context = assemble(case["artifacts"], variation, case["spec"].rubric_artifact)
        fixture["context_artifact"] = put(case["artifacts"], context.model_dump(mode="json"))
        contexts.append(context)
    digest = put(case["artifacts"], specification)
    policy = case["policy"].model_copy(update={"approved_spec_artifacts": (digest,)})
    _, _, loaded = _load_spec(case["artifacts"], digest, case["config"], policy)
    assert len(loaded) == 5
    assert all(
        isinstance(context.evidence, FrozenCalibrationEvidenceV2) for context in loaded.values()
    )
    assert all(
        set(context.evidence.declared_checks.model_dump().values()) == {"PENDING"}
        for context in loaded.values()
    )
    assert all(
        "expected_verdict" not in context.model_dump_json()
        and "expected_findings" not in context.model_dump_json()
        for context in loaded.values()
    )


@pytest.mark.parametrize(
    "route,target",
    [("anchor", role) for role in (*ELIGIBILITY, "license", "authorization", "rubric")]
    + [("subject", role) for role in (*ELIGIBILITY, "rubric")],
)
def test_private_authoring_aggregate_never_becomes_support_or_rubric(
    tmp_path, monkeypatch, route, target
):
    artifacts, anchor, subject, rubric = subject_fixture(tmp_path)
    aggregate = anchor.provenance.authoring_artifact
    if target == "rubric":
        rubric = aggregate
    elif route == "subject":
        subject = rebind(subject, check_evidence={**subject.check_evidence, target: aggregate})
    else:
        document = anchor.model_dump(mode="json")
        if target == "license":
            document["provenance"]["license_evidence_artifact"] = aggregate
        elif target == "authorization":
            document["provenance"]["usage_authorization_artifact"] = aggregate
        else:
            document["check_evidence"][target] = aggregate
        subject = rebind(subject, execution_anchor_artifact=put(artifacts, document))
    original_get = artifacts.get

    def guarded_get(digest):
        if digest == aggregate:
            pytest.fail("Private full aggregate was opened as model-visible evidence")
        return original_get(digest)

    monkeypatch.setattr(artifacts, "get", guarded_get)
    with pytest.raises(ReviewEvidenceFailure):
        if route == "subject":
            assemble(artifacts, subject, rubric)
        else:
            assemble_review_context(
                artifacts,
                subject.execution_anchor_artifact,
                rubric_artifact=rubric,
                stage="qualifier_a",
                context_id="neutral-context",
            )
