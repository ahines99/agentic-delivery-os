"""Explicit derived imports of owned fixtures; no historical qualification or execution."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_historical_linkage import linked_bundle
from test_historical_requirements import BODY
from test_qualification_preparation import IMAGE, LICENSE

from agentic_delivery.config import CommandProfile, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.historical_authorization import DerivedReferenceAuthorization
from agentic_delivery.evaluation.historical_import import (
    HistoricalAcquisitionEvidenceV2,
    HistoricalImportFailure,
    HistoricalImportRequest,
    HistoricalImportRequestV2,
    import_historical_task,
    import_historical_task_v2,
)
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    PreparationRequest,
)
from agentic_delivery.storage.store import digest_json


def put(store, document):
    return store.put(json.dumps(document, sort_keys=True).encode())


async def import_bundle(
    tmp_path, *, title="Historical issue #12", description=None, package=False, image=IMAGE
):
    description = BODY.strip() if description is None else description
    source = {
        "subject.py": "VALUE = 1\n",
        "tests/test_subject.py": "def test_original():\n    assert True\n",
        "LICENSE": LICENSE,
    }
    target = {
        **source,
        "subject.py": "VALUE = 2\n",
        "tests/test_subject.py": source["tests/test_subject.py"]
        + "\ndef test_added():\n    from subject import VALUE\n    assert VALUE == 2\n",
    }
    if package:
        source.update(
            {
                "tests/__init__.py": "from .helper import expected\n",
                "tests/helper.py": "def expected():\n    return 2\n",
            }
        )
        target.update({path: source[path] for path in ("tests/__init__.py", "tests/helper.py")})
        target["tests/test_subject.py"] = "from .helper import expected\n" + target[
            "tests/test_subject.py"
        ].replace("VALUE == 2", "VALUE == expected()")
    derivation_ref, derivation, linkage_ref, linkage, store, _ = await linked_bundle(
        tmp_path, source=source, target=target, package=package
    )
    now = datetime.now(UTC)
    commands = (
        CommandProfile(
            id="acceptance", argv=("python", "-m", "pytest", *derivation.acceptance_selectors)
        ),
        CommandProfile(id="regression", argv=("python", "-m", "pytest", "tests/test_subject.py")),
    )
    task = HistoricalTask(
        id="owned-derived",
        family="owned-family",
        split="development",
        repository_url="https://github.com/example/synthetic",
        base_sha=derivation.base_sha,
        issue_url=linkage.issue_url,
        license_id="MIT",
        item=WorkItem(
            id="owned-item",
            repository="example/synthetic",
            title=title,
            description=description,
            risk_tier=1,
            acceptance_criteria=(
                {
                    "id": "AC-1",
                    "description": "Owned criterion only",
                    "verification_type": "unit_test",
                },
            ),
        ),
        snapshot_artifact=derivation.source_snapshot_artifact,
        oracle_artifact=derivation.oracle_artifact,
        reference_snapshot_artifact=derivation.executable_reference_artifact,
        reference_patch_artifact=derivation.production_patch_artifact,
        image=image,
        acceptance_commands=(commands[0],),
        regression_commands=(commands[1],),
        reviewers=("owned-a", "owned-b"),
        qualification_mode="independent-agents-v2",
        qualification_artifact="0" * 64,
    )
    digest = qualification_task_digest(task.model_dump(mode="json"))
    license_ref = put(
        store,
        dict(
            schema_version=1,
            repository=derivation.repository,
            base_sha=derivation.base_sha,
            source_snapshot_artifact=derivation.source_snapshot_artifact,
            license_id="MIT",
            license_path="LICENSE",
            license_url=f"https://github.com/example/synthetic/blob/{derivation.base_sha}/LICENSE",
            license_text_sha256=hashlib.sha256(LICENSE.encode()).hexdigest(),
        ),
    )
    parent = dict(
        schema_version=1,
        issuer="owned-controller",
        decision="AUTHORIZED",
        task_manifest_digest=digest,
        repository=derivation.repository,
        base_sha=derivation.base_sha,
        source_url="https://example.test/owned",
        source_revision="b" * 40,
        issue_url=linkage.issue_url,
        license_evidence_artifact=license_ref,
        rights_scope="REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
        issued_at=(now - timedelta(hours=2)).isoformat(),
        expires_at=(now + timedelta(hours=2)).isoformat(),
        rationale="Owned synthetic attestation; no actual historical legal clearance or admission.",
    )
    parent_ref = put(store, parent)
    provenance = dict(
        repository=derivation.repository,
        base_sha=derivation.base_sha,
        source_task_id="owned-source",
        source_url=parent["source_url"],
        source_revision=parent["source_revision"],
        source_snapshot_artifact=derivation.source_snapshot_artifact,
        issue_url=linkage.issue_url,
        license_id="MIT",
        license_url=f"https://github.com/example/synthetic/blob/{derivation.base_sha}/LICENSE",
        license_evidence_artifact=license_ref,
        usage_authorization_artifact=parent_ref,
        rights_scope=parent["rights_scope"],
    )
    authorization = DerivedReferenceAuthorization(
        schema_version=1,
        kind="derived-historical-data-authorization",
        decision="AUTHORIZED",
        purpose="HISTORICAL_EVALUATION_DATA_PROCESSING",
        issuer="owned-controller",
        parent_authorization_artifact=parent_ref,
        task_manifest_digest=digest,
        derivation_artifact=derivation_ref,
        linkage_artifact=linkage_ref,
        repository_id=derivation.repository_id,
        source_snapshot_artifact=derivation.source_snapshot_artifact,
        accepted_snapshot_artifact=derivation.accepted_snapshot_artifact,
        oracle_artifact=derivation.oracle_artifact,
        production_patch_artifact=derivation.production_patch_artifact,
        executable_reference_artifact=derivation.executable_reference_artifact,
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        rationale=parent["rationale"],
    )
    authorization_ref = put(store, authorization.model_dump(mode="json"))
    reference = dict(
        schema_version=2,
        kind="historical-derived-reference",
        task_manifest_digest=digest,
        repository=derivation.repository,
        base_sha=derivation.base_sha,
        accepted_commit=derivation.accepted_commit,
        accepted_commit_url=f"https://github.com/example/synthetic/commit/{derivation.accepted_commit}",
        issue_url=linkage.issue_url,
        source_snapshot_artifact=derivation.source_snapshot_artifact,
        oracle_artifact=derivation.oracle_artifact,
        reference_snapshot_artifact=derivation.executable_reference_artifact,
        reference_patch_artifact=derivation.production_patch_artifact,
        derivation_artifact=derivation_ref,
        linkage_artifact=linkage_ref,
        derivation_authorization_artifact=authorization_ref,
    )
    preparation = PreparationRequest(
        schema_version=1,
        task_artifact=put(store, task.model_dump(mode="json")),
        provenance_artifact=put(store, provenance),
        reference_provenance_artifact=put(store, reference),
    )
    baseline = json.loads(store.get(derivation.request.baseline_acquisition_artifact))
    acquired = HistoricalAcquisitionEvidenceV2(
        schema_version=2,
        kind="derived-historical-acquisition",
        source_scope="FULL_REPOSITORY",
        repository=derivation.repository,
        base_sha=derivation.base_sha,
        source_task_id=provenance["source_task_id"],
        source_url=provenance["source_url"],
        source_revision=provenance["source_revision"],
        task_manifest_digest=digest,
        task_spec_digest=digest_json(task.item.model_dump(mode="json")),
        source_snapshot_artifact=derivation.source_snapshot_artifact,
        source_inventory=baseline["source_inventory"],
        accepted_snapshot_artifact=derivation.accepted_snapshot_artifact,
        derivation_artifact=derivation_ref,
        linkage_artifact=linkage_ref,
        requirements_capture_artifact=linkage.requirements_capture_artifact,
        usage_authorization_artifact=parent_ref,
        derivation_authorization_artifact=authorization_ref,
        acquired_at=now,
    )
    request = HistoricalImportRequestV2(
        schema_version=2,
        kind="derived-historical-import",
        preparation=preparation,
        acquisition_artifact=put(store, acquired.model_dump(mode="json")),
    )
    repository = RepositoryConfig(
        id="example/synthetic",
        github_owner="example",
        github_name="synthetic",
        commands=commands,
        model_data_authorized=True,
        sandbox_image=image,
        protected_paths=(),
    )
    output, worker = tmp_path / "output", tmp_path / "worker"
    output.mkdir(exist_ok=True)
    worker.mkdir(exist_ok=True)
    options = dict(
        settings=Settings(repositories=(repository,)),
        policy=PreparationPolicy(
            schema_version=1,
            policy_version="mvp-1",
            authorized_issuers=("owned-controller",),
            approved_authorization_artifacts=(parent_ref, authorization_ref),
        ),
        protected_artifacts=store,
        output_root=output,
        worker_root=worker,
        now=now,
    )
    return request, options, task, acquired


@pytest.mark.parametrize("package", [False, True])
@pytest.mark.asyncio
async def test_explicit_v2_import_preserves_all_source_and_stays_unqualified(tmp_path, package):
    request, options, task, _ = await import_bundle(tmp_path, package=package)
    store = options["protected_artifacts"]
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    result = import_historical_task_v2(request, **options)
    assert result.schema_version == 2 and result.status == "IMPORTED_NOT_QUALIFIED"
    assert not result.admitted and not result.execution_authorized
    assert result.task_artifact == request.preparation.task_artifact
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert import_historical_task_v2(request, **options) == result
    assert BODY not in result.model_dump_json() and "VALUE =" not in result.model_dump_json()
    with pytest.raises(ValueError):
        task.worker_input(store)
    old = HistoricalImportRequest(
        schema_version=1,
        preparation=request.preparation,
        acquisition_artifact=request.acquisition_artifact,
    )
    with pytest.raises(HistoricalImportFailure):
        import_historical_task(old, **options)


@pytest.mark.parametrize(
    "field",
    [
        "repository",
        "base_sha",
        "source_task_id",
        "source_url",
        "source_revision",
        "task_manifest_digest",
        "task_spec_digest",
        "source_snapshot_artifact",
        "accepted_snapshot_artifact",
        "derivation_artifact",
        "linkage_artifact",
        "requirements_capture_artifact",
        "usage_authorization_artifact",
        "derivation_authorization_artifact",
        "source_inventory",
        "acquired_at",
    ],
)
@pytest.mark.asyncio
async def test_rehashed_v2_envelope_cannot_override_chain(tmp_path, field):
    request, options, _, acquired = await import_bundle(tmp_path)
    store = options["protected_artifacts"]
    value = acquired.model_dump(mode="json")
    if field == "repository":
        value[field] = "other/repo"
    elif field in {"base_sha", "source_revision"}:
        value[field] = "c" * 40
    elif field == "source_task_id":
        value[field] = "other"
    elif field == "source_url":
        value[field] = "https://example.test/another"
    elif field == "source_inventory":
        value[field] = value[field][1:]
    elif field == "acquired_at":
        value[field] = (options["now"] + timedelta(seconds=1)).isoformat()
    else:
        value[field] = "d" * 64
    request = request.model_copy(update={"acquisition_artifact": put(store, value)})
    before = set(store.root.rglob("*"))
    with pytest.raises(HistoricalImportFailure, match="^Derived historical import refused$"):
        import_historical_task_v2(request, **options)
    assert set(store.root.rglob("*")) == before


@pytest.mark.parametrize(
    "defect",
    ["parent_pin", "derived_pin", "expired", "current_title", "changed_body", "qualified_task"],
)
@pytest.mark.asyncio
async def test_current_rights_and_safe_requirements_required(tmp_path, defect):
    request, options, task, acquired = await import_bundle(tmp_path)
    store = options["protected_artifacts"]
    if defect.endswith("pin"):
        remaining = (
            acquired.derivation_authorization_artifact
            if defect == "parent_pin"
            else acquired.usage_authorization_artifact
        )
        options["policy"] = options["policy"].model_copy(
            update={"approved_authorization_artifacts": (remaining,)}
        )
    elif defect == "expired":
        options["now"] += timedelta(hours=1)
    else:
        value = task.model_dump(mode="json")
        if defect == "current_title":
            value["item"]["title"] = "Synthetic current title"
        elif defect == "changed_body":
            value["item"]["description"] += "altered"
        else:
            value["qualification_artifact"] = "e" * 64
        request = request.model_copy(
            update={
                "preparation": request.preparation.model_copy(
                    update={"task_artifact": put(store, value)}
                )
            }
        )
    before = set(store.root.rglob("*"))
    with pytest.raises(HistoricalImportFailure):
        import_historical_task_v2(request, **options)
    assert set(store.root.rglob("*")) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Synthetic current title"},
        {"description": BODY.strip() + " modified requirement"},
    ],
)
@pytest.mark.asyncio
async def test_even_fully_rebound_and_allowlisted_task_cannot_use_current_title_or_other_body(
    tmp_path, changes
):
    request, options, _, _ = await import_bundle(tmp_path, **changes)
    store = options["protected_artifacts"]
    before = set(store.root.rglob("*"))
    with pytest.raises(HistoricalImportFailure):
        import_historical_task_v2(request, **options)
    assert set(store.root.rglob("*")) == before
