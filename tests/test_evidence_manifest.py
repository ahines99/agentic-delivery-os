"""Synthetic control-plane fixtures test admission, not real benchmark qualification."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from agentic_delivery.agents.contracts import (
    BuildProposal,
    CriterionTests,
    FileEdit,
    ImplementationPlan,
    ReviewResult,
)
from agentic_delivery.agents.evidence import validate_manifest
from agentic_delivery.agents.pipeline import build_and_review, diff_files
from agentic_delivery.config import CommandProfile, ModelConfig, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.github import GitHubPublisher
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.policy.engine import POLICY_VERSION
from agentic_delivery.repository.impact import impact_report
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import Base
from agentic_delivery.storage.store import Store, digest_json


def put(artifacts: ArtifactStore, value: object) -> str:
    return artifacts.put(json.dumps(value, sort_keys=True).encode())


def manifest_fixture(tmp_path: Path) -> tuple[Settings, RepositoryConfig, dict]:
    """All receipts here are explicitly fabricated unit-test inputs, not run evidence."""
    command = CommandProfile(id="pytest", argv=("python", "-m", "pytest", "-q"))
    repository = RepositoryConfig(
        id="test/repo",
        github_owner="test",
        github_name="repo",
        github_repository_id=777,
        commands=(command,),
        model_data_authorized=True,
        sandbox_image="sha256:" + "f" * 64,
    )
    settings = Settings(
        repositories=(repository,),
        artifact_root=tmp_path,
        publication_enabled=True,
        github_app_id=123,
        github_installation_id=456,
        github_private_key_env="TEST_GITHUB_PRIVATE_KEY",
        model=ModelConfig(
            provider="anthropic",
            model="unit-fixture-no-provider-call",
            input_microdollars_per_million=1,
            output_microdollars_per_million=1,
            rate_card_version="unit-fixture",
        ),
    )
    artifacts = ArtifactStore(tmp_path)
    base = {
        "app.py": "def value(): return 1\n",
        "tests/test_existing.py": (
            "from app import value\ndef test_existing(): assert value() >= 1\n"
        ),
    }
    candidate = {
        **base,
        "app.py": "def value(): return 2\n",
        "tests/test_new.py": "from app import value\ndef test_new(): assert value() == 2\n",
    }
    item = WorkItem(
        id="fixture-ticket",
        title="Return two",
        description="Change value to return exactly two.",
        repository=repository.id,
        risk_tier=1,
        acceptance_criteria=(
            {"id": "AC-1", "description": "Returns two", "verification_type": "unit_test"},
        ),
    )
    item_data = item.model_dump(mode="json")
    plan = ImplementationPlan(
        disposition="READY",
        summary="Return two and verify behavior",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Update value and add test",),
        files=("app.py", "tests/test_new.py"),
        verification=("pytest",),
        rollback="Revert the candidate",
        assumptions=(),
    )
    plan_data = plan.model_dump(mode="json")
    review = {
        "decision": "APPROVE",
        "summary": "Synthetic reviewer control fixture",
        "findings": [],
        "criterion_verdicts": [{"criterion_id": "AC-1", "result": "PASS"}],
    }

    def summary(files: dict[str, str], profile: CommandProfile, nodes: list[str]) -> dict:
        binding = {
            "nonce": uuid4().hex,
            "snapshot_digest": digest_json(files),
            "command_digest": digest_json(profile.model_dump(mode="json")),
            "argv": list(profile.argv),
        }
        report = {
            "collector_version": 1,
            "binding": binding,
            "session_started": True,
            "session_finished": True,
            "main_returned": True,
            "exit_code": 0,
            "collected": nodes,
            "phases": [
                {"nodeid": node, "when": when, "outcome": "passed", "wasxfail": False}
                for node in nodes
                for when in ("setup", "call", "teardown")
            ],
            "collection_errors": [],
            "deselected": [],
        }
        receipt = {
            "exit_code": 0,
            "stdout": "synthetic fixture, not evidence of a real execution",
            "stderr": "",
            "elapsed_seconds": 0.1,
            "image": repository.sandbox_image,
            "timed_out": False,
            "verification_report": report,
            "report_error": None,
            "command_id": profile.id,
            "argv": list(profile.argv),
            "snapshot_digest": digest_json(files),
            "verification_binding": binding,
            "collector_profile": "image-owned-pytest-v1",
            "workflow_id": "run-1",
        }
        return {
            "passed": True,
            "commands": [
                {
                    "command_id": profile.id,
                    "passed": True,
                    "observed_passing_tests": len(nodes),
                    "artifact_digest": put(artifacts, receipt),
                    "exit_code": 0,
                    "timed_out": False,
                    "reason": "Synthetic control fixture",
                }
            ],
            "snapshot_digest": digest_json(files),
            "image": repository.sandbox_image,
        }

    baseline = summary(base, command, ["tests/test_existing.py::test_existing"])
    validation = summary(
        candidate, command, ["tests/test_existing.py::test_existing", "tests/test_new.py::test_new"]
    )
    criterion = summary(
        candidate,
        CommandProfile(id="AC-1", argv=("python", "-m", "pytest", "tests/test_new.py::test_new")),
        ["tests/test_new.py::test_new"],
    )
    approved_plan = {
        "plan": plan_data,
        "base_sha": "a" * 40,
        "snapshot_digest": put(artifacts, base),
    }
    return (
        settings,
        repository,
        {
            "schema_version": 1,
            "workflow_id": "run-1",
            "repository": repository.id,
            "base_sha": "a" * 40,
            "candidate_digest": digest_json(candidate),
            "candidate_artifact": put(artifacts, candidate),
            "spec_digest": digest_json(item_data),
            "assessed_item_artifact": put(artifacts, item_data),
            "plan_digest": digest_json(plan_data),
            "approved_plan_digest": put(artifacts, approved_plan),
            "input_spec_digest": digest_json(item_data),
            "input_spec_artifact": put(artifacts, item_data),
            "configuration_digest": settings.execution_digest(repository.id),
            "model_configuration": settings.model.model_dump(mode="json"),
            "policy_version": POLICY_VERSION,
            "baseline": baseline,
            "attempts": [
                {
                    "iteration": 0,
                    "review": review,
                    "validation": validation,
                    "criteria": {"AC-1": criterion},
                }
            ],
            "review_artifact": put(artifacts, review),
            "preflight": {
                "image": repository.sandbox_image,
                "checks": dict.fromkeys(
                    [
                        "nonroot",
                        "no_socket",
                        "readonly_root",
                        "egress_denied",
                        "no_new_privileges",
                        "capabilities_dropped",
                        "workspace_bounded",
                    ],
                    True,
                ),
            },
            "impact": impact_report(candidate, ("app.py", "tests/test_new.py")),
            "diff_digest": artifacts.put(diff_files(base, candidate).encode()),
            "limitation": "Synthetic unit control bundle; not benchmark evidence",
        },
    )


def test_complete_reference_chain_passes_structural_publication_admission(tmp_path: Path) -> None:
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    verified, candidate = validate_manifest(settings, repository, "run-1", put(artifacts, manifest))
    assert verified == manifest
    assert candidate["app.py"] == "def value(): return 2\n"


@pytest.mark.parametrize("configured_src", [False, True])
def test_rehashed_criterion_cannot_add_or_remove_operator_import_profile(
    tmp_path: Path, configured_src: bool
) -> None:
    """Fabricated unit receipts prove binding rejection, not real execution."""
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)

    def rewrite(summary: dict, src: bool) -> None:
        result = summary["commands"][0]
        receipt = json.loads(artifacts.get(result["artifact_digest"]))
        argv = [arg for arg in receipt["argv"] if arg not in {"-o", "pythonpath=src"}]
        if src:
            argv.extend(("-o", "pythonpath=src"))
        receipt["argv"] = argv
        command = CommandProfile(id=receipt["command_id"], argv=tuple(argv))
        binding = {
            **receipt["verification_binding"],
            "argv": argv,
            "command_digest": digest_json(command.model_dump(mode="json")),
        }
        receipt["verification_binding"] = binding
        receipt["verification_report"]["binding"] = binding
        result["artifact_digest"] = put(artifacts, receipt)

    if configured_src:
        repository = repository.model_copy(
            update={
                "commands": tuple(
                    command.model_copy(update={"argv": (*command.argv, "-o", "pythonpath=src")})
                    for command in repository.commands
                )
            }
        )
        settings = settings.model_copy(update={"repositories": (repository,)})
        manifest["configuration_digest"] = settings.execution_digest(repository.id)
        rewrite(manifest["baseline"], True)
        rewrite(manifest["attempts"][0]["validation"], True)
        rewrite(manifest["attempts"][0]["criteria"]["AC-1"], True)
    # Establish a consistent synthetic chain first, then alter only its criterion
    # import policy and rehash the full receipt/binding/manifest chain.
    validate_manifest(settings, repository, "run-1", put(artifacts, manifest))
    rewrite(manifest["attempts"][0]["criteria"]["AC-1"], not configured_src)
    with pytest.raises(ValueError, match="Criterion import profile"):
        validate_manifest(settings, repository, "run-1", put(artifacts, manifest))


def test_manifest_rejects_mixed_operator_import_profiles(tmp_path: Path) -> None:
    settings, repository, manifest = manifest_fixture(tmp_path)
    original = repository.commands[0]
    repository = repository.model_copy(
        update={
            "commands": (
                original,
                original.model_copy(
                    update={"id": "src", "argv": (*original.argv, "-o", "pythonpath=src")}
                ),
            )
        }
    )
    settings = settings.model_copy(update={"repositories": (repository,)})
    manifest["configuration_digest"] = settings.execution_digest(repository.id)
    with pytest.raises(ValueError, match="inconsistent import profiles"):
        validate_manifest(settings, repository, "run-1", put(ArtifactStore(tmp_path), manifest))


@pytest.mark.parametrize(
    "defect",
    [
        "legacy",
        "unknown_field",
        "workflow",
        "repository",
        "policy",
        "configuration",
        "model",
        "base",
        "specification",
        "input",
        "plan",
        "candidate",
        "diff",
        "impact",
        "preflight",
        "missing_criterion",
        "conflicting_review",
        "blocking_review",
        "duplicate_verdict",
        "repair_limit",
        "missing_artifact",
    ],
)
async def test_tampered_or_stale_chain_denied_before_any_github_request(
    tmp_path: Path, defect: str
) -> None:
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    final = manifest["attempts"][-1]
    if defect == "legacy":
        del manifest["schema_version"]
    elif defect == "unknown_field":
        manifest["override"] = "ignore checks"
    elif defect in {
        "workflow",
        "repository",
        "policy",
        "configuration",
        "model",
        "base",
        "specification",
        "input",
        "plan",
        "candidate",
        "diff",
    }:
        fields = {
            "workflow": ("workflow_id", "other-run"),
            "repository": ("repository", "other/repo"),
            "policy": ("policy_version", "old-policy"),
            "configuration": ("configuration_digest", "0" * 64),
            "model": (
                "model_configuration",
                {**manifest["model_configuration"], "model": "other-model"},
            ),
            "base": ("base_sha", "b" * 40),
            "specification": ("spec_digest", "0" * 64),
            "input": ("input_spec_digest", "0" * 64),
            "plan": ("plan_digest", "0" * 64),
            "candidate": ("candidate_digest", "0" * 64),
            "diff": ("diff_digest", artifacts.put(b"unrelated diff")),
        }
        field, value = fields[defect]
        manifest[field] = value
    elif defect == "impact":
        manifest["impact"]["changed"] = ["app.py"]
    elif defect == "preflight":
        manifest["preflight"]["checks"]["egress_denied"] = False
    elif defect == "missing_criterion":
        final["criteria"] = {}
    elif defect == "conflicting_review":
        final["review"]["decision"] = "REQUEST_CHANGES"
    elif defect in {"blocking_review", "duplicate_verdict"}:
        review = json.loads(artifacts.get(manifest["review_artifact"]))
        if defect == "blocking_review":
            review["findings"] = [
                {
                    "severity": "blocking",
                    "path": "app.py",
                    "description": "Unresolved",
                    "evidence": "Fixture",
                }
            ]
        else:
            review["criterion_verdicts"] *= 2
        final["review"] = review
        manifest["review_artifact"] = put(artifacts, review)
    elif defect == "repair_limit":
        manifest["attempts"] *= 4
    elif defect == "missing_artifact":
        manifest["approved_plan_digest"] = "0" * 64
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise AssertionError("Invalid evidence must not request credentials or publish")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ValueError):
            await GitHubPublisher(settings, repository, client).publish(
                "run-1", put(artifacts, manifest)
            )
    assert calls == []


@pytest.mark.parametrize("scope", ["baseline", "suite", "criterion"])
@pytest.mark.parametrize(
    "defect",
    [
        "absent_report",
        "wrong_workflow",
        "stale_binding",
        "missing_phase",
        "nonzero_exit",
        "wrong_image",
    ],
)
def test_passing_flags_cannot_override_receipt_bytes(
    tmp_path: Path, scope: str, defect: str
) -> None:
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    summary = {
        "baseline": manifest["baseline"],
        "suite": manifest["attempts"][-1]["validation"],
        "criterion": manifest["attempts"][-1]["criteria"]["AC-1"],
    }[scope]
    result = summary["commands"][0]
    receipt = json.loads(artifacts.get(result["artifact_digest"]))
    if defect == "absent_report":
        receipt["verification_report"] = None
        receipt["stdout"] = "9999 passed"
    elif defect == "wrong_workflow":
        receipt["workflow_id"] = "unrelated-run"
    elif defect == "stale_binding":
        receipt["verification_report"]["binding"]["snapshot_digest"] = "0" * 64
    elif defect == "missing_phase":
        receipt["verification_report"]["phases"].pop()
    elif defect == "nonzero_exit":
        receipt["exit_code"] = 1
    elif defect == "wrong_image":
        receipt["image"] = "sha256:" + "0" * 64
    result["artifact_digest"] = put(artifacts, receipt)
    with pytest.raises(ValueError):
        validate_manifest(settings, repository, "run-1", put(artifacts, manifest))


def test_rehashed_candidate_cannot_modify_protected_existing_tests(tmp_path: Path) -> None:
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    candidate = json.loads(artifacts.get(manifest["candidate_artifact"]))
    candidate["tests/test_existing.py"] = "def test_existing(): assert True\n"
    manifest["candidate_artifact"] = put(artifacts, candidate)
    manifest["candidate_digest"] = digest_json(candidate)
    with pytest.raises(ValueError, match="protected"):
        validate_manifest(settings, repository, "run-1", put(artifacts, manifest))


@pytest.mark.integration
@pytest.mark.parametrize("layout", ["flat", "src"])
async def test_actual_pipeline_produces_compatible_receipt_reference_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    """Real Docker receipts with controlled model fixtures; no live model/review claim."""
    image_variable = "TEST_SRC_SANDBOX_IMAGE" if layout == "src" else "TEST_SANDBOX_IMAGE"
    image = os.environ.get(image_variable)
    if not image:
        pytest.skip(f"{image_variable} is not configured")
    settings, repository, template = manifest_fixture(tmp_path / "artifacts")
    repository = repository.model_copy(update={"sandbox_image": image})
    settings = settings.model_copy(update={"repositories": (repository,)})
    artifacts = ArtifactStore(settings.artifact_root)
    original = WorkItem.model_validate_json(artifacts.get(template["input_spec_artifact"]))
    approved = json.loads(artifacts.get(template["approved_plan_digest"]))
    plan = ImplementationPlan.model_validate(approved["plan"])
    base = json.loads(artifacts.get(approved["snapshot_digest"]))
    candidate = json.loads(artifacts.get(template["candidate_artifact"]))
    if layout == "src":
        base["src/app.py"] = base.pop("app.py")
        candidate["src/app.py"] = candidate.pop("app.py")
        plan = plan.model_copy(update={"files": ("src/app.py", "tests/test_new.py")})
        approved["plan"] = plan.model_dump(mode="json")
        approved["snapshot_digest"] = put(artifacts, base)
        template["approved_plan_digest"] = put(artifacts, approved)
        repository = repository.model_copy(
            update={
                "commands": tuple(
                    command.model_copy(update={"argv": (*command.argv, "-o", "pythonpath=src")})
                    for command in repository.commands
                )
            }
        )
        settings = settings.model_copy(update={"repositories": (repository,)})
    review = ReviewResult.model_validate_json(artifacts.get(template["review_artifact"]))
    engine = create_database(f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    store = Store(engine)
    run = store.submit(original, actor="fixture", key=uuid4().hex, budget=settings.budget)

    async def generated(self, workflow_id, operation_id, *, instructions, context, output_type):
        if output_type is ReviewResult:
            return review
        assert output_type is BuildProposal
        return BuildProposal(
            summary="Controlled synthetic builder fixture",
            edits=tuple(
                FileEdit(
                    path=path,
                    original_sha256=hashlib.sha256(base[path].encode()).hexdigest()
                    if path in base
                    else None,
                    content=content,
                )
                for path, content in candidate.items()
                if base.get(path) != content
            ),
            criterion_tests=(
                CriterionTests(criterion_id="AC-1", tests=("tests/test_new.py::test_new",)),
            ),
        )

    monkeypatch.setattr(StructuredModel, "generate", generated)
    result = await build_and_review(
        run["workflow_id"],
        original,
        plan,
        base,
        "a" * 40,
        settings,
        store,
        repository,
        approved_plan_digest=template["approved_plan_digest"],
    )
    assert result["state"] == "LOCAL_REVIEW_READY"
    manifest, validated_candidate = validate_manifest(
        settings, repository, run["workflow_id"], result["manifest_digest"]
    )
    assert manifest["schema_version"] == 1
    assert validated_candidate == candidate
    criterion = manifest["attempts"][-1]["criteria"]["AC-1"]["commands"][0]
    receipt = json.loads(artifacts.get(criterion["artifact_digest"]))
    assert receipt["argv"] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *(["-o", "pythonpath=src"] if layout == "src" else []),
        "tests/test_new.py::test_new",
    ]
    assert receipt["verification_binding"]["argv"] == receipt["argv"]
