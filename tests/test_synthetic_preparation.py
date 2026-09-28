"""Newly authored toy data only; no historical claims or provider execution."""

import hashlib
import json
from datetime import timedelta

import pytest
from test_qualification_preparation import IMAGE, NOW, patch_between, put

from agentic_delivery.config import CommandProfile, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_preparation import (
    LicenseEvidence,
    PreparationPolicy,
    PreparationRequest,
    parse_provenance,
    parse_task,
    parse_usage_authorization,
    prepare_qualification,
)
from agentic_delivery.evaluation.synthetic_types import SyntheticTask
from agentic_delivery.storage.artifacts import ArtifactStore

RIGHTS = (
    "Newly authored project-owned toy fixture for internal synthetic validation and authorized "
    "model processing only. This test attestation grants no public redistribution rights and "
    "does not claim rights over third-party code, datasets or historical tickets.\n"
)
IDENTITY = dict(
    schema_version=1,
    kind="project-owned-synthetic",
    purpose="SYNTHETIC_VALIDATION",
    construction_revision="d" * 40,  # Explicit synthetic construction-code identity for tests.
)
LICENSE_ID = "LicenseRef-Project-Owned-Internal"
SCOPE = "PROJECT_OWNED_FIXTURE_AND_INTERNAL_MODEL_PROCESSING"


@pytest.fixture
def owned_fixture(tmp_path):
    store = ArtifactStore(tmp_path / "protected")
    output, worker = tmp_path / "output", tmp_path / "worker"
    output.mkdir()
    worker.mkdir()
    source = {
        "app.py": "def value():\n    return 1\n",
        "tests/test_existing.py": (
            "from app import value\ndef test_type():\n    assert isinstance(value(), int)\n"
        ),
        "FIXTURE_RIGHTS.txt": RIGHTS,
    }
    oracle = {
        "tests/test_behavior.py": (
            "from app import value\ndef test_value():\n    assert value() == 2\n"
        )
    }
    changed = {**source, "app.py": "def value():\n    return 2\n"}
    commands = tuple(
        CommandProfile(id=name, argv=("python", "-m", "pytest", path))
        for name, path in (
            ("acceptance", "tests/test_behavior.py"),
            ("regression", "tests/test_existing.py"),
        )
    )
    task = SyntheticTask(
        **IDENTITY,
        authoring_artifact=put(store, {"fixture": "newly authored preparation-only toy"}),
        id="owned-toy",
        family="owned-toy-family",
        split="development",
        license_id=LICENSE_ID,
        item=WorkItem(
            id="owned-toy",
            title="Return the required constant",
            description="Authored toy task",
            repository="fixture/repo",
            risk_tier=1,
            acceptance_criteria=(
                {
                    "id": "AC-1",
                    "description": "value returns two",
                    "verification_type": "unit_test",
                },
            ),
        ),
        snapshot_artifact=put(store, source),
        oracle_artifact=put(store, oracle),
        reference_patch_artifact=store.put(patch_between(source, changed)),
        reference_snapshot_artifact=put(store, {**changed, **oracle}),
        image=IMAGE,
        acceptance_commands=(commands[0],),
        regression_commands=(commands[1],),
        reviewers=("owned-context-a", "owned-context-b"),
        qualification_mode="independent-agents-v2",
        qualification_artifact="0" * 64,
    )
    task_digest = qualification_task_digest(task.model_dump(mode="json"))
    license_record = {
        **IDENTITY,
        "repository": "fixture/repo",
        "source_snapshot_artifact": task.snapshot_artifact,
        "license_id": LICENSE_ID,
        "license_path": "FIXTURE_RIGHTS.txt",
        "license_text_sha256": hashlib.sha256(RIGHTS.encode()).hexdigest(),
    }
    authorization = {
        **IDENTITY,
        "authoring_artifact": task.authoring_artifact,
        "issuer": "owned-test-controller",
        "decision": "AUTHORIZED",
        "task_manifest_digest": task_digest,
        "repository": "fixture/repo",
        "license_evidence_artifact": put(store, license_record),
        "rights_scope": SCOPE,
        "issued_at": (NOW - timedelta(days=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "rationale": (
            "Synthetic test policy permits internal processing of this newly authored toy only."
        ),
    }
    provenance = {
        **IDENTITY,
        "authoring_artifact": task.authoring_artifact,
        "repository": "fixture/repo",
        "source_snapshot_artifact": task.snapshot_artifact,
        "license_id": LICENSE_ID,
        "license_evidence_artifact": authorization["license_evidence_artifact"],
        "usage_authorization_artifact": put(store, authorization),
        "rights_scope": SCOPE,
    }
    reference = {
        **IDENTITY,
        "method": "AUTHORED_FIXTURE_REFERENCE",
        "task_manifest_digest": task_digest,
        "repository": "fixture/repo",
        "source_snapshot_artifact": task.snapshot_artifact,
        "oracle_artifact": task.oracle_artifact,
        "reference_snapshot_artifact": task.reference_snapshot_artifact,
        "reference_patch_artifact": task.reference_patch_artifact,
    }
    request = PreparationRequest(
        schema_version=1,
        task_artifact=put(store, task.model_dump(mode="json")),
        provenance_artifact=put(store, provenance),
        reference_provenance_artifact=put(store, reference),
    )
    policy = PreparationPolicy(
        schema_version=1,
        policy_version="mvp-1",
        authorized_issuers=("owned-test-controller",),
        approved_authorization_artifacts=(provenance["usage_authorization_artifact"],),
    )
    settings = Settings(
        repositories=(
            RepositoryConfig(
                id="fixture/repo",
                github_owner="fixture",
                github_name="repo",
                commands=commands,
                model_data_authorized=True,
                sandbox_image=IMAGE,
            ),
        )
    )
    return (
        request,
        dict(
            settings=settings,
            policy=policy,
            protected_artifacts=store,
            output_root=output,
            worker_root=worker,
            now=NOW,
        ),
        task,
    )


def test_owned_toy_prepares_without_historical_claims_or_writes(owned_fixture):
    request, options, task = owned_fixture
    root = options["protected_artifacts"].root.parent
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    prepared = prepare_qualification(request, **options)
    assert prepared.status == "PREPARED_NOT_QUALIFIED"
    assert not prepared.admitted and not prepared.execution_authorized
    assert prepared.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    for claim in ("base_sha", "issue_url", "accepted_commit", "license_url"):
        assert claim not in task.model_dump_json()
    for leak in ("return 2", "test_value", RIGHTS):
        assert leak not in prepared.model_dump_json()


@pytest.mark.parametrize("action", ["worker_input", "validate_qualification"])
def test_no_synthetic_historical_capability(owned_fixture, action):
    _, options, task = owned_fixture
    with pytest.raises(ValueError, match="Synthetic"):
        getattr(task, action)(options["protected_artifacts"], authority=object())
    with pytest.raises(ValueError):
        HistoricalTask.model_validate(task.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("split", "test"),
        ("purpose", "HISTORICAL_QUALIFICATION"),
        ("kind", "unknown"),
        ("base_sha", "a" * 40),
        ("issue_url", "https://github.com/fixture/repo/issues/1"),
        ("construction_revision", "a" * 64),
    ],
)
def test_synthetic_contract_cannot_be_relabelled(owned_fixture, field, value):
    _, _, task = owned_fixture
    with pytest.raises(ValueError):
        parse_task({**task.model_dump(mode="json"), field: value})


@pytest.mark.parametrize(
    "defect", ["revoked", "expired", "license", "reference", "mixed", "image", "risk", "scope"]
)
def test_synthetic_preparation_denies_tampering_and_revocation(owned_fixture, defect):
    request, options, task = owned_fixture
    store = options["protected_artifacts"]
    if defect == "revoked":
        options["policy"] = options["policy"].model_copy(
            update={"approved_authorization_artifacts": ("f" * 64,)}
        )
    elif defect == "expired":
        options["now"] += timedelta(days=2)
    elif defect in {"license", "mixed"}:
        provenance = json.loads(store.get(request.provenance_artifact))
        if defect == "license":
            license_record = json.loads(store.get(provenance["license_evidence_artifact"]))
            license_record["license_text_sha256"] = "f" * 64
            provenance["license_evidence_artifact"] = put(store, license_record)
        else:
            del provenance["kind"]
        request = request.model_copy(update={"provenance_artifact": put(store, provenance)})
    elif defect == "reference":
        reference = json.loads(store.get(request.reference_provenance_artifact))
        reference["construction_revision"] = "f" * 40
        request = request.model_copy(
            update={"reference_provenance_artifact": put(store, reference)}
        )
    elif defect == "scope":
        options["worker_root"] = store.root
    else:
        document = task.model_dump(mode="json")
        if defect == "image":
            document["image"] = "sha256:" + "f" * 64
        else:
            document["item"]["risk_tier"] = 3
        request = request.model_copy(update={"task_artifact": put(store, document)})
    with pytest.raises(ValueError):
        prepare_qualification(request, **options)


def test_typed_parsers_and_historical_license_scope_remain_distinct(owned_fixture):
    request, options, task = owned_fixture
    store = options["protected_artifacts"]
    provenance = parse_provenance(json.loads(store.get(request.provenance_artifact)))
    authorization = parse_usage_authorization(
        json.loads(store.get(provenance.usage_authorization_artifact))
    )
    assert authorization.purpose == "SYNTHETIC_VALIDATION"
    assert parse_task(task.model_dump(mode="json")) == task
    with pytest.raises(ValueError):
        LicenseEvidence.model_validate(json.loads(store.get(provenance.license_evidence_artifact)))


@pytest.mark.parametrize("target", ["provenance", "authorization"])
def test_authoring_aggregate_binding_is_consistent_across_rights_chain(owned_fixture, target):
    request, options, _ = owned_fixture
    store = options["protected_artifacts"]
    provenance = json.loads(store.get(request.provenance_artifact))
    if target == "provenance":
        provenance["authoring_artifact"] = "f" * 64
    else:
        authorization = json.loads(store.get(provenance["usage_authorization_artifact"]))
        authorization["authoring_artifact"] = "f" * 64
        provenance["usage_authorization_artifact"] = put(store, authorization)
        options["policy"] = options["policy"].model_copy(
            update={
                "approved_authorization_artifacts": (provenance["usage_authorization_artifact"],)
            }
        )
    request = request.model_copy(update={"provenance_artifact": put(store, provenance)})
    with pytest.raises(ValueError):
        prepare_qualification(request, **options)


@pytest.mark.parametrize("target", ["tests/test_existing.py", "FIXTURE_RIGHTS.txt", "AGENTS.md"])
def test_authored_reference_still_cannot_change_original_tests_rights_or_controls(
    owned_fixture, target
):
    request, options, task = owned_fixture
    store = options["protected_artifacts"]
    source = json.loads(store.get(task.snapshot_artifact))
    oracle = json.loads(store.get(task.oracle_artifact))
    changed = {**source, "app.py": "def value():\n    return 2\n", target: "changed\n"}
    task = task.model_copy(
        update={
            "reference_patch_artifact": store.put(patch_between(source, changed)),
            "reference_snapshot_artifact": put(store, {**changed, **oracle}),
        }
    )
    digest = qualification_task_digest(task.model_dump(mode="json"))
    provenance = json.loads(store.get(request.provenance_artifact))
    authorization = json.loads(store.get(provenance["usage_authorization_artifact"]))
    authorization["task_manifest_digest"] = digest
    provenance["usage_authorization_artifact"] = put(store, authorization)
    options["policy"] = options["policy"].model_copy(
        update={"approved_authorization_artifacts": (provenance["usage_authorization_artifact"],)}
    )
    reference = json.loads(store.get(request.reference_provenance_artifact))
    reference.update(
        task_manifest_digest=digest,
        reference_patch_artifact=task.reference_patch_artifact,
        reference_snapshot_artifact=task.reference_snapshot_artifact,
    )
    request = request.model_copy(
        update={
            "task_artifact": put(store, task.model_dump(mode="json")),
            "provenance_artifact": put(store, provenance),
            "reference_provenance_artifact": put(store, reference),
        }
    )
    with pytest.raises(ValueError, match="protected controls/tests"):
        prepare_qualification(request, **options)
