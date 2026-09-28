"""Explicit synthetic imports; no fixture establishes actual rights or historical admission."""

import difflib
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from agentic_delivery.config import CommandProfile, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_preparation import (
    MAX_PATCH_BYTES,
    PreparationPolicy,
    PreparationRequest,
    apply_reference_patch,
    prepare_qualification,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

NOW = datetime(2026, 9, 28, tzinfo=UTC)
IMAGE = "sha256:" + "e" * 64
BASE = "a" * 40
LICENSE = (
    "SYNTHETIC LICENSE EVIDENCE: this test fixture grants no rights over real source, "
    "datasets, issues, or model processing; no actual task is admitted.\n"
)
SOURCE = {
    "app.py": "VALUE = 1\n",
    "tests/test_existing.py": "def test_existing():\n    assert True\n",
    "LICENSE": LICENSE,
}
ORACLE = {"tests/test_behavior.py": "def test_value():\n    assert True\n"}


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


def patch_between(source, target):
    return "".join(
        "".join(
            difflib.unified_diff(
                source.get(path, "").splitlines(keepends=True),
                target.get(path, "").splitlines(keepends=True),
                fromfile="a/" + path if path in source else "/dev/null",
                tofile="b/" + path if path in target else "/dev/null",
            )
        )
        for path in sorted(source.keys() | target.keys())
        if source.get(path) != target.get(path)
    ).encode()


@pytest.fixture
def synthetic(tmp_path):
    """A pinned *synthetic* controller policy; intentionally not production authorization."""
    store = ArtifactStore(tmp_path / "protected")
    output, worker = tmp_path / "output", tmp_path / "worker"
    output.mkdir()
    worker.mkdir()

    def build(
        *,
        source=None,
        oracle=None,
        reference=None,
        patch=None,
        task_changes=None,
        provenance_changes=None,
        license_changes=None,
        authorization_changes=None,
        reference_changes=None,
        repository_changes=None,
        policy_changes=None,
    ):
        source = dict(SOURCE if source is None else source)
        oracle = dict(ORACLE if oracle is None else oracle)
        changed = {**source, "app.py": "VALUE = 2\n"} if reference is None else reference
        commands = (
            CommandProfile(
                id="acceptance", argv=("python", "-m", "pytest", "tests/test_behavior.py")
            ),
            CommandProfile(
                id="regression", argv=("python", "-m", "pytest", "tests/test_existing.py")
            ),
        )
        task = HistoricalTask(
            id="synthetic-task",
            family="synthetic-family",
            split="development",
            repository_url="https://github.com/fixture/repo",
            base_sha=BASE,
            issue_url="https://github.com/fixture/repo/issues/1",
            license_id="MIT",
            item=WorkItem(
                id="synthetic-issue",
                title="Synthetic task",
                description="Fixture only",
                repository="fixture/repo",
                risk_tier=1,
                acceptance_criteria=(
                    {
                        "id": "AC-1",
                        "description": "Synthetic criterion",
                        "verification_type": "unit_test",
                    },
                ),
            ),
            snapshot_artifact=put(store, source),
            oracle_artifact=put(store, oracle),
            reference_snapshot_artifact=put(store, {**changed, **oracle}),
            reference_patch_artifact=store.put(
                patch if patch is not None else patch_between(source, changed)
            ),
            image=IMAGE,
            acceptance_commands=(commands[0],),
            regression_commands=(commands[1],),
            reviewers=("synthetic-context-a", "synthetic-context-b"),
            qualification_mode="independent-agents-v1",
            qualification_artifact="0" * 64,
        ).model_dump(mode="json")
        task.update(task_changes or {})
        task_digest = qualification_task_digest(
            HistoricalTask.model_validate(task).model_dump(mode="json")
        )
        license_record = {
            "schema_version": 1,
            "repository": "fixture/repo",
            "base_sha": BASE,
            "source_snapshot_artifact": task["snapshot_artifact"],
            "license_id": "MIT",
            "license_path": "LICENSE",
            "license_url": f"https://github.com/fixture/repo/blob/{BASE}/LICENSE",
            "license_text_sha256": hashlib.sha256(source.get("LICENSE", "").encode()).hexdigest(),
            **(license_changes or {}),
        }
        license_digest = put(store, license_record)
        authorization = {
            "schema_version": 1,
            "issuer": "synthetic-controller",
            "decision": "AUTHORIZED",
            "task_manifest_digest": task_digest,
            "repository": "fixture/repo",
            "base_sha": BASE,
            "source_url": "https://example.test/synthetic",
            "source_revision": "b" * 40,
            "issue_url": task["issue_url"],
            "license_evidence_artifact": license_digest,
            "rights_scope": "REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
            "issued_at": (NOW - timedelta(days=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            "rationale": (
                "Synthetic trusted-controller attestation for unit tests, "
                "not actual legal clearance."
            ),
            **(authorization_changes or {}),
        }
        authorization_digest = put(store, authorization)
        provenance = {
            "repository": "fixture/repo",
            "base_sha": BASE,
            "source_task_id": "synthetic-source",
            "source_url": "https://example.test/synthetic",
            "source_revision": "b" * 40,
            "source_snapshot_artifact": task["snapshot_artifact"],
            "issue_url": task["issue_url"],
            "license_id": "MIT",
            "license_url": license_record["license_url"],
            "license_evidence_artifact": license_digest,
            "usage_authorization_artifact": authorization_digest,
            "rights_scope": "REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
            **(provenance_changes or {}),
        }
        reference_record = {
            "schema_version": 1,
            "task_manifest_digest": task_digest,
            "repository": "fixture/repo",
            "base_sha": BASE,
            "accepted_commit": "c" * 40,
            "accepted_commit_url": f"https://github.com/fixture/repo/commit/{'c' * 40}",
            "issue_url": task["issue_url"],
            "source_snapshot_artifact": task["snapshot_artifact"],
            "oracle_artifact": task["oracle_artifact"],
            "reference_snapshot_artifact": task["reference_snapshot_artifact"],
            "reference_patch_artifact": task["reference_patch_artifact"],
            **(reference_changes or {}),
        }
        request = PreparationRequest(
            schema_version=1,
            task_artifact=put(store, task),
            provenance_artifact=put(store, provenance),
            reference_provenance_artifact=put(store, reference_record),
        )
        repo = RepositoryConfig(
            **{
                "id": "fixture/repo",
                "github_owner": "fixture",
                "github_name": "repo",
                "commands": commands,
                "model_data_authorized": True,
                "sandbox_image": IMAGE,
                **(repository_changes or {}),
            }
        )
        policy = PreparationPolicy(
            **{
                "schema_version": 1,
                "policy_version": "mvp-1",
                "authorized_issuers": ("synthetic-controller",),
                "approved_authorization_artifacts": (authorization_digest,),
                **(policy_changes or {}),
            }
        )
        kwargs = dict(
            settings=Settings(repositories=(repo,)),
            policy=policy,
            protected_artifacts=store,
            output_root=output,
            worker_root=worker,
            now=NOW,
        )
        return request, kwargs, task

    return build


def test_preparation_is_read_only_metadata_and_not_admission(synthetic):
    request, kwargs, task = synthetic()
    root = kwargs["protected_artifacts"].root.parent
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = prepare_qualification(request, **kwargs)
    assert result.status == "PREPARED_NOT_QUALIFIED"
    assert result.execution_authorized is False and result.admitted is False
    assert result.task_manifest_digest == qualification_task_digest(task)
    assert result.baseline_snapshot_digest == digest_json({**SOURCE, **ORACLE})
    assert result.reference_snapshot_digest == digest_json(
        {**SOURCE, **ORACLE, "app.py": "VALUE = 2\n"}
    )
    serialized = result.model_dump_json()
    for secret in ("VALUE =", "test_value", "test_existing", LICENSE, "synthetic-context-a"):
        assert secret not in serialized
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, FileNotFoundError)):
        HistoricalTask.model_validate(task).worker_input(kwargs["protected_artifacts"])


@pytest.mark.parametrize(
    "changes",
    [
        {"repository_changes": {"model_data_authorized": False}},
        {"repository_changes": {"sandbox_image": "sha256:" + "f" * 64}},
        {"repository_changes": {"commands": ()}},
        {"policy_changes": {"authorized_issuers": ("other",)}},
        {"policy_changes": {"approved_authorization_artifacts": ("0" * 64,)}},
        {"authorization_changes": {"expires_at": NOW.isoformat()}},
        {"authorization_changes": {"issued_at": (NOW + timedelta(seconds=1)).isoformat()}},
        {"authorization_changes": {"task_manifest_digest": "f" * 64}},
        {"authorization_changes": {"source_revision": "f" * 40}},
        {"authorization_changes": {"repository": "other/repo"}},
        {"provenance_changes": {"base_sha": "f" * 40}},
        {"provenance_changes": {"issue_url": "https://github.com/other/repo/issues/1"}},
        {"license_changes": {"license_text_sha256": "f" * 64}},
        {"license_changes": {"license_url": "https://github.com/fixture/repo/blob/main/LICENSE"}},
        {"reference_changes": {"accepted_commit": BASE}},
        {"reference_changes": {"reference_patch_artifact": "f" * 64}},
        {"reference_changes": {"accepted_commit_url": "https://example.test/commit"}},
        {"task_changes": {"qualification_mode": "unverified"}},
        {"task_changes": {"qualification_artifact": "f" * 64}},
        {"task_changes": {"reviewers": ["a", "b", "c"]}},
        {"source": {**SOURCE, "LICENSE": "dummy"}},
    ],
)
def test_rejects_unbound_unapproved_or_incomplete_imports(synthetic, changes):
    request, kwargs, _ = synthetic(**changes)
    with pytest.raises(ValueError):
        prepare_qualification(request, **kwargs)


@pytest.mark.parametrize("field", ["license_evidence_artifact", "usage_authorization_artifact"])
def test_nonempty_dummy_evidence_is_not_a_record(synthetic, field):
    _, kwargs, _ = synthetic()
    digest = kwargs["protected_artifacts"].put(b"some nonempty evidence")
    request, kwargs, _ = synthetic(
        provenance_changes={field: digest},
        policy_changes={"approved_authorization_artifacts": (digest,)},
    )
    with pytest.raises(ValueError):
        prepare_qualification(request, **kwargs)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_existing.py",
        "nested/test_original.py",
        "nested/original_test.py",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "AGENTS.md",
        "infra/control.txt",
        "LICENSE",
    ],
)
def test_original_tests_and_control_files_cannot_change(synthetic, path):
    source = {**SOURCE, path: "# original\n"} if path != "LICENSE" else SOURCE
    reference = {**source, "app.py": "VALUE = 2\n", path: "# changed\n"}
    request, kwargs, _ = synthetic(source=source, reference=reference)
    with pytest.raises(ValueError, match="protected"):
        prepare_qualification(request, **kwargs)


@pytest.mark.parametrize(
    "oracle",
    [
        {"app.py": "pass\n"},
        {"APP.py": "pass\n"},
        {"tests/conftest.py": "pass\n"},
        {"pyproject.toml": "pass\n"},
        {"tests/test_behavior.py/child.py": "pass\n"},
    ],
)
def test_oracle_collision_and_control_rejected(synthetic, oracle):
    source = (
        SOURCE
        if "tests/test_behavior.py/child.py" not in oracle
        else {**SOURCE, "tests/test_behavior.py": "pass\n"}
    )
    request, kwargs, _ = synthetic(source=source, oracle=oracle)
    with pytest.raises(ValueError):
        prepare_qualification(request, **kwargs)


def test_patch_must_reproduce_declared_reference(synthetic):
    patch = patch_between(SOURCE, {**SOURCE, "app.py": "VALUE = 99\n"})
    request, kwargs, _ = synthetic(patch=patch)
    with pytest.raises(ValueError, match="differs from reference"):
        prepare_qualification(request, **kwargs)


@pytest.mark.parametrize("pair", [(0, 1), (0, 2), (1, 2)])
@pytest.mark.parametrize("relation", ["same", "nested", "reverse"])
def test_scope_overlap_rejected(synthetic, pair, relation):
    request, kwargs, _ = synthetic()
    paths = [kwargs["protected_artifacts"].root, kwargs["output_root"], kwargs["worker_root"]]
    left, right = pair
    if relation == "same":
        paths[right] = paths[left]
    elif relation == "nested":
        paths[right] = paths[left] / "nested"
        paths[right].mkdir()
    else:
        paths[left] = paths[right] / "nested"
        paths[left].mkdir()
    kwargs.update(
        protected_artifacts=ArtifactStore(paths[0]), output_root=paths[1], worker_root=paths[2]
    )
    with pytest.raises(ValueError, match="disjoint"):
        prepare_qualification(request, **kwargs)


def test_configured_repository_scope_also_protected(synthetic):
    _, kwargs, _ = synthetic()
    request, kwargs, _ = synthetic(repository_changes={"local_repository": kwargs["output_root"]})
    with pytest.raises(ValueError, match="disjoint"):
        prepare_qualification(request, **kwargs)


def test_changed_code_requires_risk_escalation(synthetic):
    request, kwargs, _ = synthetic(reference={**SOURCE, "app.py": "eval('1')\n"})
    with pytest.raises(ValueError, match="Dynamic execution"):
        prepare_qualification(request, **kwargs)


def test_duplicate_json_is_rejected(synthetic):
    request, kwargs, _ = synthetic()
    digest = kwargs["protected_artifacts"].put(b'{"repository":"x","repository":"y"}')
    request = request.model_copy(update={"provenance_artifact": digest})
    with pytest.raises(ValueError, match="Duplicate JSON"):
        prepare_qualification(request, **kwargs)


def test_exact_patch_supports_multiple_hunks_creation_and_deletion():
    source = {"app.py": "".join(f"line {i}\n" for i in range(20)), "remove.txt": "old\n"}
    target = {
        "app.py": source["app.py"].replace("line 1\n", "one\n").replace("line 19\n", "last\n"),
        "new.py": "VALUE = 1\n",
    }
    assert apply_reference_patch(source, patch_between(source, target)) == target


@pytest.mark.parametrize(
    "patch",
    [
        b"",
        b"x" * (MAX_PATCH_BYTES + 1),
        b"\xff",
        b"diff --git a/app.py b/app.py\n",
        b"GIT binary patch\n",
        b"old mode 100644\nnew mode 100755\n",
        b"--- a/app.py\n+++ b/other.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n",
        b"--- a/../app.py\n+++ b/../app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n",
        b"--- a/app.py\tdate\n+++ b/app.py\tdate\n",
        b"--- a/app.py\r\n+++ b/app.py\r\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-WRONG\n+VALUE = 2\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -2 +1 @@\n-VALUE = 1\n+VALUE = 2\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +2 @@\n-VALUE = 1\n+VALUE = 2\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2",
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
        b"\\ No newline at end of file\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n VALUE = 1\n",
        b"--- /dev/null\n+++ b/app.py\n@@ -0,0 +1 @@\n+VALUE = 2\n",
        b"--- a/app.py\n+++ /dev/null\n@@ -0,0 +1 @@\n+extra\n",
        b"--- a/app.py\n+++ b/app.py\n@@ -0,0 +0,0 @@\n",
    ],
    ids=lambda value: "patch-" + hashlib.sha256(value).hexdigest()[:8],
)
def test_unsupported_or_inexact_patch_fails_closed(patch):
    with pytest.raises(ValueError):
        apply_reference_patch({"app.py": "VALUE = 1\n"}, patch)


def test_duplicate_file_patch_rejected():
    source = {"app.py": "VALUE = 1\n"}
    patch = patch_between(source, {"app.py": "VALUE = 2\n"})
    with pytest.raises(ValueError, match="Duplicate"):
        apply_reference_patch(source, patch + patch)


def test_patch_cannot_introduce_case_or_directory_collision():
    source = {"app.py": "VALUE = 1\n"}
    for path in ("APP.py", "app.py/child.py"):
        with pytest.raises(ValueError, match="collision|colliding"):
            apply_reference_patch(source, patch_between(source, {**source, path: "pass\n"}))


def test_snapshot_and_patch_resource_limits():
    with pytest.raises(ValueError, match="too many files"):
        apply_reference_patch({f"file{i}.py": "x\n" for i in range(1001)}, b"x\n")
    with pytest.raises(ValueError, match="File exceeds"):
        apply_reference_patch({"large.py": "x" * (256 * 1024 + 1)}, b"x\n")
    source = {f"file{i}.py": "VALUE = 1\n" for i in range(51)}
    target = {path: "VALUE = 2\n" for path in source}
    with pytest.raises(ValueError, match="too many patch files"):
        apply_reference_patch(source, patch_between(source, target))
    with pytest.raises(ValueError, match="Too many patch hunks"):
        apply_reference_patch(
            {"app.py": "VALUE = 1\n"},
            b"--- a/app.py\n+++ b/app.py\n"
            + b"".join(f"@@ -0,0 +{i + 1} @@\n+new\n".encode() for i in range(1001)),
        )


def test_reference_syntax_error_does_not_expose_solution(synthetic):
    request, kwargs, _ = synthetic(reference={**SOURCE, "app.py": "if HIDDEN_SOLUTION\n"})
    with pytest.raises(ValueError, match="syntax profile") as caught:
        prepare_qualification(request, **kwargs)
    assert "HIDDEN_SOLUTION" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_intake_risk_and_budget_are_rechecked(synthetic):
    request, kwargs, _ = synthetic()
    store = kwargs["protected_artifacts"]
    task = json.loads(store.get(request.task_artifact))
    task["item"]["risk_tags"] = ["secrets"]
    changed = request.model_copy(update={"task_artifact": put(store, task)})
    with pytest.raises(ValueError, match="risk escalation"):
        prepare_qualification(changed, **kwargs)
    task["item"]["risk_tags"] = []
    task["budget"]["model_microdollars"] += 1
    changed = request.model_copy(update={"task_artifact": put(store, task)})
    with pytest.raises(ValueError, match="budget exceeds"):
        prepare_qualification(changed, **kwargs)


def test_configured_unsupported_pytest_command_still_denied(synthetic):
    request, kwargs, _ = synthetic()
    store = kwargs["protected_artifacts"]
    task = json.loads(store.get(request.task_artifact))
    task["acceptance_commands"][0]["argv"] = ["python", "-m", "pytest", "--override-ini", "x"]
    command = CommandProfile.model_validate(task["acceptance_commands"][0])
    repo = kwargs["settings"].repositories[0]
    repo = repo.model_copy(update={"commands": (command, repo.commands[1])})
    kwargs["settings"] = Settings(repositories=(repo,))
    changed = request.model_copy(update={"task_artifact": put(store, task)})
    with pytest.raises(ValueError, match="Unsupported pytest"):
        prepare_qualification(changed, **kwargs)


def test_linked_scope_rejected(synthetic):
    request, kwargs, _ = synthetic()
    link = kwargs["worker_root"].parent / "linked-worker"
    try:
        os.symlink(kwargs["worker_root"], link, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit directory symlink creation")
    kwargs["worker_root"] = link
    with pytest.raises(ValueError, match="Linked"):
        prepare_qualification(request, **kwargs)


def test_no_naive_clock_or_disabled_admission(synthetic):
    request, kwargs, _ = synthetic()
    kwargs["now"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="Aware clock"):
        prepare_qualification(request, **kwargs)
    kwargs["now"] = NOW
    kwargs["settings"] = kwargs["settings"].model_copy(update={"admissions_enabled": False})
    with pytest.raises(ValueError, match="admissions are disabled"):
        prepare_qualification(request, **kwargs)
