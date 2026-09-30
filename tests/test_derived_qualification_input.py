"""Owned reconstructed Git/linkage fixtures; no historical inputs or live execution."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from program_fixtures import program_ledger
from test_historical_linkage import linked_bundle
from test_qualification_preparation import IMAGE, LICENSE

from agentic_delivery.config import CommandProfile, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation import qualification_runtime as runtime
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.historical_authorization import DerivedReferenceAuthorization
from agentic_delivery.evaluation.qualification import (
    EvidenceSummary,
    QualificationInput,
    qualification_task_digest,
)
from agentic_delivery.evaluation.qualification_input_resolution import (
    DerivedQualificationInput,
    resolve_qualification_input,
)
from agentic_delivery.evaluation.qualification_inputs import materialize_qualification_input
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    PreparationRequest,
    ReferenceProvenance,
    ReferenceProvenanceV2,
    prepare_qualification,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
    RuntimeFailure,
    run_deterministic_qualification,
)
from agentic_delivery.evaluation.qualification_v2 import (
    ELIGIBILITY,
    assemble_review_context,
)
from agentic_delivery.execution.docker import ExecutionResult
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def put(store, document):
    return store.put(json.dumps(document, sort_keys=True).encode())


async def derived_case(tmp_path, *, item_changes=None, rights_lifetime=timedelta(hours=1)):
    """Reusable complete owned proofs, with independently reconstructable metadata."""
    source = {
        "src/subject.py": "def answer():\n    return 1\n",
        "tests/test_subject.py": (
            "import unittest\nfrom subject import answer\n"
            "def test_original():\n    assert answer() >= 1\n"
        ),
        "LICENSE": LICENSE,
    }
    target = {
        **source,
        "src/subject.py": "def answer():\n    return 2\n",
        "tests/test_subject.py": source["tests/test_subject.py"]
        + "class Behavior(unittest.TestCase):\n"
        + "    def test_answer(self):\n        self.assertEqual(answer(), 2)\n",
    }
    derived_ref, derived, linkage_ref, linkage, store, scopes = await linked_bundle(
        tmp_path, source=source, target=target
    )
    now = datetime.now(UTC)
    commands = (
        CommandProfile(
            id="acceptance",
            argv=("python", "-m", "pytest", "-o", "pythonpath=src", *derived.acceptance_selectors),
        ),
        CommandProfile(
            id="regression",
            argv=(
                "python",
                "-m",
                "pytest",
                "-o",
                "pythonpath=src",
                "tests/test_subject.py::test_original",
            ),
        ),
    )
    task = HistoricalTask(
        id="owned-derived",
        family="owned-derived-family",
        split="development",
        repository_url="https://github.com/example/synthetic",
        base_sha=derived.base_sha,
        issue_url=linkage.issue_url,
        license_id="MIT",
        item=WorkItem(
            id="owned-issue",
            title=f"Historical issue #{linkage.issue_number}",
            description=store.get(linkage.requirements_artifact).decode("utf-8").strip(),
            repository=derived.repository,
            risk_tier=1,
            acceptance_criteria=(
                {"id": "AC-1", "description": "Returns two", "verification_type": "unit_test"},
            ),
        ).model_copy(update=item_changes or {}),
        snapshot_artifact=derived.source_snapshot_artifact,
        oracle_artifact=derived.oracle_artifact,
        reference_snapshot_artifact=derived.executable_reference_artifact,
        reference_patch_artifact=derived.production_patch_artifact,
        image=IMAGE,
        acceptance_commands=(commands[0],),
        regression_commands=(commands[1],),
        reviewers=("owned-review-a", "owned-review-b"),
        qualification_mode="independent-agents-v2",
        qualification_artifact="0" * 64,
    )
    manifest = qualification_task_digest(task.model_dump(mode="json"))
    license_url = f"https://github.com/{derived.repository}/blob/{derived.base_sha}/LICENSE"
    license_ref = put(
        store,
        {
            "schema_version": 1,
            "repository": derived.repository,
            "base_sha": derived.base_sha,
            "source_snapshot_artifact": derived.source_snapshot_artifact,
            "license_id": "MIT",
            "license_path": "LICENSE",
            "license_url": license_url,
            "license_text_sha256": hashlib.sha256(LICENSE.encode()).hexdigest(),
        },
    )
    authorization_ref = put(
        store,
        {
            "schema_version": 1,
            "issuer": "owned-fixture-controller",
            "decision": "AUTHORIZED",
            "task_manifest_digest": manifest,
            "repository": derived.repository,
            "base_sha": derived.base_sha,
            "source_url": "https://example.test/owned-dataset",
            "source_revision": "3" * 40,
            "issue_url": linkage.issue_url,
            "license_evidence_artifact": license_ref,
            "rights_scope": "REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
            "issued_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "rationale": "Owned synthetic attestation for protocol tests; grants no real rights.",
        },
    )
    provenance = {
        "repository": derived.repository,
        "base_sha": derived.base_sha,
        "source_task_id": "owned-source",
        "source_url": "https://example.test/owned-dataset",
        "source_revision": "3" * 40,
        "source_snapshot_artifact": derived.source_snapshot_artifact,
        "issue_url": linkage.issue_url,
        "license_id": "MIT",
        "license_url": license_url,
        "license_evidence_artifact": license_ref,
        "usage_authorization_artifact": authorization_ref,
        "rights_scope": "REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
    }
    derived_authorization = DerivedReferenceAuthorization(
        schema_version=1,
        kind="derived-historical-data-authorization",
        decision="AUTHORIZED",
        purpose="HISTORICAL_EVALUATION_DATA_PROCESSING",
        issuer="owned-fixture-controller",
        parent_authorization_artifact=authorization_ref,
        task_manifest_digest=manifest,
        derivation_artifact=derived_ref,
        linkage_artifact=linkage_ref,
        repository_id=derived.repository_id,
        source_snapshot_artifact=derived.source_snapshot_artifact,
        accepted_snapshot_artifact=derived.accepted_snapshot_artifact,
        oracle_artifact=derived.oracle_artifact,
        production_patch_artifact=derived.production_patch_artifact,
        executable_reference_artifact=derived.executable_reference_artifact,
        issued_at=now - timedelta(hours=1),
        expires_at=now + rights_lifetime,
        rationale="Owned derived synthetic data attestation; no real historical data rights.",
    )
    derived_authorization_ref = put(store, derived_authorization.model_dump(mode="json"))
    reference = ReferenceProvenanceV2(
        schema_version=2,
        kind="historical-derived-reference",
        task_manifest_digest=manifest,
        repository=derived.repository,
        base_sha=derived.base_sha,
        accepted_commit=derived.accepted_commit,
        accepted_commit_url=f"https://github.com/{derived.repository}/commit/{derived.accepted_commit}",
        issue_url=linkage.issue_url,
        source_snapshot_artifact=derived.source_snapshot_artifact,
        oracle_artifact=derived.oracle_artifact,
        reference_snapshot_artifact=derived.executable_reference_artifact,
        reference_patch_artifact=derived.production_patch_artifact,
        derivation_artifact=derived_ref,
        linkage_artifact=linkage_ref,
        derivation_authorization_artifact=derived_authorization_ref,
    )
    request = PreparationRequest(
        schema_version=1,
        task_artifact=put(store, task.model_dump(mode="json")),
        provenance_artifact=put(store, provenance),
        reference_provenance_artifact=put(store, reference.model_dump(mode="json")),
    )
    repository = RepositoryConfig(
        id=derived.repository,
        github_owner="example",
        github_name="synthetic",
        commands=commands,
        sandbox_image=IMAGE,
        model_data_authorized=True,
    )
    output, worker = tmp_path / "output", scopes[0]
    output.mkdir()
    worker.mkdir()
    args = {
        "settings": Settings(repositories=(repository,)),
        "policy": PreparationPolicy(
            schema_version=1,
            policy_version="mvp-1",
            authorized_issuers=("owned-fixture-controller",),
            approved_authorization_artifacts=(authorization_ref, derived_authorization_ref),
        ),
        "protected_artifacts": store,
        "output_root": output,
        "worker_root": worker,
        "now": now,
    }
    return {
        "request": request,
        "args": args,
        "store": store,
        "task": task,
        "provenance": provenance,
        "reference": reference,
        "derived": derived,
        "linkage": linkage,
        "repository": repository,
    }


def fabricated_input(case):
    """Fabricated receipts exercise proof validation, not actual Docker or qualification."""
    store, task, derived = case["store"], case["task"], case["derived"]
    support = store.put(b"Owned preliminary evidence; no actual historical qualification.")
    executions = []
    for variant in ("baseline", "reference"):
        files = json.loads(
            store.get(
                derived.executable_baseline_artifact
                if variant == "baseline"
                else derived.executable_reference_artifact
            )
        )
        for suite, command, nodes in (
            ("acceptance", task.acceptance_commands[0], derived.acceptance_selectors),
            ("regression", task.regression_commands[0], ("tests/test_subject.py::test_original",)),
        ):
            for repetition in (1, 2, 3):
                failed = variant == "baseline" and suite == "acceptance"
                binding = {
                    "nonce": uuid4().hex,
                    "snapshot_digest": digest_json(files),
                    "command_digest": digest_json(command.model_dump(mode="json")),
                    "argv": list(command.argv),
                }
                report = {
                    "collector_version": 1,
                    "binding": binding,
                    "session_started": True,
                    "session_finished": True,
                    "main_returned": True,
                    "exit_code": int(failed),
                    "collected": list(nodes),
                    "collection_errors": [],
                    "deselected": [],
                    "phases": [
                        {
                            "nodeid": node,
                            "when": when,
                            "outcome": "failed" if failed and when == "call" else "passed",
                            "wasxfail": False,
                        }
                        for node in nodes
                        for when in ("setup", "call", "teardown")
                    ],
                }
                receipt = {
                    "exit_code": int(failed),
                    "stdout": "owned fabricated receipt",
                    "stderr": "",
                    "elapsed_seconds": 0.01,
                    "image": task.image,
                    "timed_out": False,
                    "verification_report": report,
                    "report_error": None,
                    "command_id": command.id,
                    "argv": list(command.argv),
                    "snapshot_digest": digest_json(files),
                    "verification_binding": binding,
                    "collector_profile": "image-owned-pytest-v1",
                    "workflow_id": f"owned-{variant}-{suite}-{repetition}",
                }
                executions.append(
                    {
                        "variant": variant,
                        "suite": suite,
                        "repetition": repetition,
                        "receipt_artifact": put(store, receipt),
                    }
                )
    return QualificationInput(
        schema_version=1,
        task_id=task.id,
        task_manifest_digest=qualification_task_digest(task.model_dump(mode="json")),
        task_spec=task.item,
        provenance=case["provenance"],
        checks=dict.fromkeys(ELIGIBILITY, "PASS"),
        check_evidence=dict.fromkeys(ELIGIBILITY, support),
        findings=tuple(
            {
                "check": name,
                "status": "PASS",
                "summary": "Owned fabricated protocol evidence.",
                "evidence_refs": (support,),
            }
            for name in sorted(ELIGIBILITY)
        ),
        risk_tier=1,
        family=task.family,
        split=task.split,
        image=task.image,
        baseline_snapshot_artifact=derived.executable_baseline_artifact,
        reference_snapshot_artifact=derived.executable_reference_artifact,
        reference_patch_artifact=derived.production_patch_artifact,
        oracle_artifact=derived.oracle_artifact,
        acceptance_command=task.acceptance_commands[0],
        regression_command=task.regression_commands[0],
        behavior_nodes=derived.acceptance_selectors,
        regression_nodes=("tests/test_subject.py::test_original",),
        executions=tuple(executions),
    )


def wrapper_for(case, spec=None):
    request = case["request"]
    return DerivedQualificationInput(
        schema_version=2,
        kind="historical-derived-qualification-input",
        qualification_input=spec or fabricated_input(case),
        task_artifact=request.task_artifact,
        provenance_artifact=request.provenance_artifact,
        reference_provenance_artifact=request.reference_provenance_artifact,
    )


@pytest.fixture
async def derived(tmp_path):
    return await derived_case(tmp_path)


async def test_preparation_and_outer_input_reconstruct_without_writes(derived, monkeypatch):
    request, args, store = derived["request"], derived["args"], derived["store"]
    wrapper = wrapper_for(derived)
    outer = put(store, wrapper.model_dump(mode="json"))
    rubric = store.put(b"Owned rubric; require complete requirement and execution evidence.")

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only resolution/preparation must not write")

    monkeypatch.setattr(store, "put", forbidden)
    prepared = prepare_qualification(request, **args)
    assert prepared.request == request and prepared.admitted is False
    resolved = resolve_qualification_input(store, outer, expected_preparation=request)
    assert resolved.input_artifact == outer
    assert resolved.qualification_input == wrapper.qualification_input
    assert outer in resolved.forbidden_artifacts
    context = assemble_review_context(
        store, outer, rubric_artifact=rubric, stage="qualifier_a", context_id="owned-review-a"
    )
    assert context.evidence.qualification_input_artifact == outer
    assert context.evidence.source_files == json.loads(store.get(derived["task"].snapshot_artifact))
    assert context.evidence.oracle_files == json.loads(store.get(derived["task"].oracle_artifact))


@pytest.mark.parametrize("path", ["src/subject.py", "tests/test_subject.py"])
async def test_current_protected_paths_invalidate_both_original_change_roles(derived, path):
    repository = derived["repository"].model_copy(update={"protected_paths": (path,)})
    args = {**derived["args"], "settings": Settings(repositories=(repository,))}
    with pytest.raises(ValueError, match="currently protected"):
        prepare_qualification(derived["request"], **args)


async def test_scope_overlap_still_denies_preparation(derived):
    args = {**derived["args"], "worker_root": derived["store"].root}
    with pytest.raises(ValueError, match="disjoint"):
        prepare_qualification(derived["request"], **args)


@pytest.mark.parametrize("field", ["title", "description"])
async def test_rehashed_unbound_requirements_fail_shared_preparation_and_review(tmp_path, field):
    case = await derived_case(tmp_path, item_changes={field: "Unbound post-acceptance wording"})
    # All task/provenance/rights digests are coherently recomputed by the fixture.
    # The trusted capture, not the presence of valid self-consistent pins, is decisive.
    with pytest.raises(ValueError, match="wording"):
        prepare_qualification(case["request"], **case["args"])
    wrapper = wrapper_for(case)
    outer = put(case["store"], wrapper.model_dump(mode="json"))
    with pytest.raises(ValueError, match="Protected qualification input"):
        resolve_qualification_input(case["store"], outer, expected_preparation=case["request"])
    with pytest.raises(ValueError):
        assemble_review_context(
            case["store"],
            outer,
            rubric_artifact=case["store"].put(b"Owned review rubric."),
            stage="qualifier_a",
            context_id="owned-review-a",
        )


async def test_wrapper_stripping_and_alternate_preparation_refs_fail_closed(derived):
    wrapper = wrapper_for(derived)
    store, request = derived["store"], derived["request"]
    inner = put(store, wrapper.qualification_input.model_dump(mode="json"))
    with pytest.raises(ValueError, match="Protected qualification input"):
        resolve_qualification_input(store, inner, expected_preparation=request)
    outer = put(store, wrapper.model_dump(mode="json"))
    for field in ("task_artifact", "provenance_artifact", "reference_provenance_artifact"):
        altered = request.model_copy(update={field: "f" * 64})
        with pytest.raises(ValueError, match="Protected qualification input"):
            resolve_qualification_input(store, outer, expected_preparation=altered)
    with pytest.raises(ValueError):
        QualificationInput.model_validate_json(store.get(outer))
    with pytest.raises(ValueError):
        ReferenceProvenance.model_validate(derived["reference"].model_dump(mode="json"))


@pytest.mark.parametrize("field", ["task_id", "task_spec", "family", "image", "behavior_nodes"])
async def test_rehashed_inner_metadata_cannot_change_bound_task_or_selectors(derived, field):
    wrapper = wrapper_for(derived)
    data = wrapper.model_dump(mode="json")
    if field == "task_spec":
        data["qualification_input"][field]["description"] = "Different requirements"
    elif field == "behavior_nodes":
        data["qualification_input"][field] = ["tests/test_subject.py::test_original"]
    else:
        data["qualification_input"][field] = "sha256:" + "f" * 64 if field == "image" else "changed"
    with pytest.raises(ValueError, match="Protected qualification input"):
        resolve_qualification_input(derived["store"], put(derived["store"], data))


async def test_entire_computed_closure_is_forbidden_as_support_and_rubric(derived):
    store = derived["store"]
    wrapper = wrapper_for(derived)
    outer = put(store, wrapper.model_dump(mode="json"))
    resolved = resolve_qualification_input(store, outer)
    rubric = store.put(b"Owned rubric describing evidence completeness.")
    for forbidden in resolved.forbidden_artifacts:
        # Some raw accepted file hashes are not independent artifact-store objects.
        # The check must refuse the identity before attempting supporting-text reads.
        changed = wrapper.model_dump(mode="json")
        changed["qualification_input"]["check_evidence"]["oracle"] = forbidden
        with pytest.raises(ValueError):
            assemble_review_context(
                store,
                put(store, changed),
                rubric_artifact=rubric,
                stage="qualifier_a",
                context_id="owned-review-a",
            )
        with pytest.raises(ValueError):
            assemble_review_context(
                store,
                outer,
                rubric_artifact=forbidden,
                stage="qualifier_a",
                context_id="owned-review-a",
            )


@pytest.mark.parametrize(
    "kind",
    [
        "derived-historical-acquisition",
        "derived-historical-import",
        "imported-derived-historical-task",
        "provider-reported-merged-pr-linkage-v1",
    ],
)
async def test_derived_aggregate_aliases_cannot_be_supporting_text_or_rubric(derived, kind):
    store = derived["store"]
    aggregate = put(store, {"schema_version": 2, "kind": kind, "untrusted": "opaque"})
    wrapper = wrapper_for(derived)
    outer = put(store, wrapper.model_dump(mode="json"))
    with pytest.raises(ValueError):
        assemble_review_context(
            store,
            outer,
            rubric_artifact=aggregate,
            stage="qualifier_a",
            context_id="owned-review-a",
        )
    changed = wrapper.model_dump(mode="json")
    changed["qualification_input"]["check_evidence"]["family"] = aggregate
    with pytest.raises(ValueError):
        assemble_review_context(
            store,
            put(store, changed),
            rubric_artifact=store.put(b"Owned rubric"),
            stage="qualifier_a",
            context_id="owned-review-a",
        )


class OwnedDerivedRunner:
    """Controlled report transport only; never claims real sandbox execution."""

    calls = 0
    hook = None
    cancelled = False

    def __init__(self, image):
        self.image = image

    async def preflight(self):
        return {"image": self.image, "checks": dict.fromkeys(runtime.PREFLIGHT_CHECKS, True)}

    async def run(self, files, argv, *, verification_binding, **kwargs):
        type(self).calls += 1
        nodes = pytest_selectors(argv)
        failed = (
            nodes[0] != "tests/test_subject.py::test_original"
            and files["src/subject.py"] == "def answer():\n    return 1\n"
        )
        report = {
            "collector_version": 1,
            "binding": verification_binding,
            "session_started": True,
            "session_finished": True,
            "main_returned": True,
            "exit_code": int(failed),
            "collected": list(nodes),
            "collection_errors": [],
            "deselected": [],
            "phases": [
                {
                    "nodeid": node,
                    "when": phase,
                    "outcome": "failed" if failed and phase == "call" else "passed",
                    "wasxfail": False,
                }
                for node in nodes
                for phase in ("setup", "call", "teardown")
            ],
        }
        if type(self).hook is not None:
            try:
                await type(self).hook()
            except asyncio.CancelledError:
                type(self).cancelled = True
                raise
        return ExecutionResult(
            int(failed),
            "owned controlled fixture",
            "",
            0.01,
            self.image,
            verification_report=report,
        )


@pytest.fixture
def derived_runtime(derived, monkeypatch, tmp_path):
    args = derived["args"]
    now = datetime.now(UTC)
    request = DeterministicRequest(
        preparation=derived["request"],
        behavior_nodes=derived["derived"].acceptance_selectors,
        regression_nodes=("tests/test_subject.py::test_original",),
    )
    grant = RuntimeAuthorization(
        account_id="owned-derived-runtime",
        request_digest=digest_json(request.model_dump(mode="json")),
        execution_config_digest=args["settings"].execution_digest(derived["task"].item.repository),
        preparation_policy_digest=digest_json(args["policy"].model_dump(mode="json")),
        budget=derived["task"].budget,
        infrastructure_microdollars=100_000,
        total_microdollars=5_100_000,
        microdollars_per_second=1,
        rate_card_version="owned-controlled-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    ledger = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_derived_runtime.db'}")
    state = {"now": None}
    OwnedDerivedRunner.calls = 0
    OwnedDerivedRunner.hook = None
    OwnedDerivedRunner.cancelled = False
    monkeypatch.setattr(runtime, "DockerRunner", OwnedDerivedRunner)
    monkeypatch.setattr(runtime, "POLL_SECONDS", 0.01)
    options = {
        "settings_provider": lambda: args["settings"],
        "policy_provider": lambda: args["policy"],
        "authorization_provider": lambda: grant,
        "protected_artifacts": derived["store"],
        "output_artifacts": ArtifactStore(args["output_root"]),
        "worker_root": args["worker_root"],
        "ledger": ledger,
        "clock": lambda: state["now"] or datetime.now(UTC),
    }
    yield request, grant, options, state
    ledger.engine.dispose()


async def test_materialization_checkpoints_outer_wrapper_and_resumes_without_calls(
    derived, derived_runtime
):
    request, grant, options, _ = derived_runtime
    result = await run_deterministic_qualification(request, **options)
    store = derived["store"]
    support = store.put(b"Owned preliminary qualification findings.")
    arguments = {
        key: options[key]
        for key in ("protected_artifacts", "output_artifacts", "worker_root", "ledger")
    }
    arguments.update(
        authorization=grant,
        settings=derived["args"]["settings"],
        policy=derived["args"]["policy"],
        now=datetime.now(UTC),
        check_evidence=dict.fromkeys(ELIGIBILITY, support),
        findings=tuple(
            EvidenceSummary(
                check=check,
                status="PENDING",
                summary="Owned controlled preliminary finding.",
                evidence_refs=(support,),
            )
            for check in sorted(ELIGIBILITY)
        ),
    )
    outer = materialize_qualification_input(request, result["evidence_artifact"], **arguments)
    wrapper = DerivedQualificationInput.model_validate_json(store.get(outer))
    assert (
        wrapper.reference_provenance_artifact == request.preparation.reference_provenance_artifact
    )
    assert (
        options["ledger"].checkpoint_receipt(grant.account_id, "runtime-review-input-v1")[
            "artifact_digest"
        ]
        == outer
    )
    assert (
        materialize_qualification_input(request, result["evidence_artifact"], **arguments) == outer
    )
    assert await run_deterministic_qualification(request, **options) == result
    assert OwnedDerivedRunner.calls == 12


async def test_shorter_derived_rights_expiry_cancels_active_batch(derived, derived_runtime):
    request, grant, options, state = derived_runtime
    # Keep the parent and runtime grants live; only derived-data authorization expires.
    store = derived["store"]
    reference = derived["reference"]
    record = json.loads(store.get(reference.derivation_authorization_artifact))
    record["expires_at"] = (grant.issued_at + timedelta(seconds=5)).isoformat()
    new_rights = put(store, record)
    new_reference = reference.model_copy(update={"derivation_authorization_artifact": new_rights})
    preparation = request.preparation.model_copy(
        update={"reference_provenance_artifact": put(store, new_reference.model_dump(mode="json"))}
    )
    request = request.model_copy(update={"preparation": preparation})
    policy = derived["args"]["policy"].model_copy(
        update={
            "approved_authorization_artifacts": (
                derived["provenance"]["usage_authorization_artifact"],
                new_rights,
            )
        }
    )
    grant = grant.model_copy(
        update={
            "request_digest": digest_json(request.model_dump(mode="json")),
            "preparation_policy_digest": digest_json(policy.model_dump(mode="json")),
        }
    )
    options["authorization_provider"] = lambda: grant
    options["policy_provider"] = lambda: policy

    async def expire():
        state["now"] = grant.issued_at + timedelta(seconds=6)
        await asyncio.Event().wait()

    OwnedDerivedRunner.hook = expire
    with pytest.raises(RuntimeFailure):
        await asyncio.wait_for(run_deterministic_qualification(request, **options), timeout=10)
    assert OwnedDerivedRunner.calls == 1 and OwnedDerivedRunner.cancelled
    assert (
        options["ledger"].checkpoint_receipt(grant.account_id, "deterministic-complete-v1") is None
    )
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **options)
    assert OwnedDerivedRunner.calls == 1
