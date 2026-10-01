"""Owned src-layout fixtures: exact grammar, import origins and real collector execution."""

import json
import os
import runpy
from pathlib import Path

import pytest

from agentic_delivery.config import CommandProfile
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.verification import pytest_import_options, pytest_selectors, verify
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

PREFIX = ("python", "-m", "pytest")
DIRECTIVE = ("-o", "pythonpath=src")
NODE = "tests/test_owned.py::TestOwned::test_origin"
COLLECTOR = Path(__file__).resolve().parents[1] / "infra/docker/collector.py"


@pytest.fixture
def collector():
    # Load only the repository-owned launcher; never any historical or candidate code.
    return runpy.run_path(str(COLLECTOR))


@pytest.mark.parametrize(
    "args",
    [
        (NODE,),
        (*DIRECTIVE, NODE),
        (NODE, *DIRECTIVE),
        ("-q", *DIRECTIVE, "-p", "no:cacheprovider", NODE),
        ("-vv", "--disable-warnings", NODE),
    ],
)
def test_host_and_collector_accept_same_selectors(collector, args):
    argv = (*PREFIX, *args)
    assert pytest_selectors(argv) == (NODE,)
    assert collector["selectors"](list(argv)) == [NODE]


@pytest.mark.parametrize(
    "args",
    [
        ("-o",),
        ("-o", ""),
        (*DIRECTIVE, *DIRECTIVE, NODE),
        ("-o", "pythonpath=src", NODE, "-o", "pythonpath=src"),
        ("-o", "pythonpath=src src2", NODE),
        ("-o", "pythonpath=src\n", NODE),
        ("-o", "pythonpath=./src", NODE),
        ("-o", "pythonpath=../src", NODE),
        ("-o", "pythonpath=/workspace/src", NODE),
        ("-o", "pythonpath=src/", NODE),
        ("-o", "pythonpath=SRC", NODE),
        ("-o", "pythonpath=src;echo", NODE),
        ("-opythonpath=src", NODE),
        ("--override-ini", "pythonpath=src", NODE),
        ("--override-ini=pythonpath=src", NODE),
        ("-o", "addopts=-p bad", NODE),
        (*DIRECTIVE, "-c", "pytest.ini", NODE),
        (*DIRECTIVE, "-p", "bad", NODE),
        (*DIRECTIVE, NODE, NODE),
        (*DIRECTIVE, "tests/../bad.py"),
        (*DIRECTIVE, "tests/.git/bad.py"),
        (*DIRECTIVE, "tests/COM1.py"),
        (*DIRECTIVE, "tests/test.py "),
        (*DIRECTIVE, "tests/test.py\x00"),
        (*DIRECTIVE, "C:/outside.py"),
    ],
)
def test_host_and_collector_reject_unsupported_grammar(collector, args):
    argv = (*PREFIX, *args)
    with pytest.raises(ValueError):
        pytest_selectors(argv)
    with pytest.raises(ValueError):
        collector["selectors"](list(argv))


def test_existing_command_serialization_has_no_new_fields():
    profile = CommandProfile(id="old", argv=(*PREFIX, NODE))
    expected = {"id": "old", "argv": list((*PREFIX, NODE)), "expected_tests": 1}
    assert profile.model_dump(mode="json") == expected
    assert digest_json(profile.model_dump(mode="json")) == digest_json(expected)
    updated = CommandProfile(id="old", argv=(*PREFIX, *DIRECTIVE, NODE))
    assert digest_json(updated.model_dump(mode="json")) != digest_json(expected)


@pytest.mark.parametrize("directive", [(), DIRECTIVE])
def test_criterion_import_options_come_only_from_consistent_operator_profiles(directive):
    commands = tuple(
        CommandProfile(id=str(index), argv=(*PREFIX, *directive, selector))
        for index, selector in enumerate(("tests/test_one.py", "tests/test_two.py"))
    )
    assert pytest_import_options(commands) == directive


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ((NODE,), (*DIRECTIVE, NODE)),
        ((*DIRECTIVE, NODE), (NODE,)),
        (("-o", "pythonpath=other", NODE),),
        ((*DIRECTIVE, *DIRECTIVE, NODE),),
    ],
)
async def test_invalid_operator_import_profiles_stop_pipeline_before_effects(
    tmp_path, monkeypatch, arguments
):
    from test_evidence_manifest import manifest_fixture

    from agentic_delivery.agents import pipeline
    from agentic_delivery.domain.models import WorkItem

    settings, repository, template = manifest_fixture(tmp_path)
    repository = repository.model_copy(
        update={
            "commands": tuple(
                CommandProfile(id=str(index), argv=(*PREFIX, *args))
                for index, args in enumerate(arguments)
            )
        }
    )
    item = WorkItem.model_validate_json(
        ArtifactStore(tmp_path).get(template["input_spec_artifact"])
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid import profiles must fail before runner or model construction")

    monkeypatch.setattr(pipeline, "DockerRunner", forbidden)
    monkeypatch.setattr(pipeline, "StructuredModel", forbidden)
    with pytest.raises(ValueError):
        await pipeline.build_and_review(
            "owned-profile-denial", item, None, {}, "a" * 40, settings, None, repository
        )


def test_src_origin_validation_does_not_import_code_or_process_pth(collector, tmp_path):
    root = tmp_path / "src"
    package = root / "owned_unique_source_fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise RuntimeError('must not import')\n")
    (root / "owned_unique_module_fixture.py").write_text("raise RuntimeError('must not import')\n")
    (root / "owned_unique_namespace_fixture").mkdir()
    (root / "untrusted.pth").write_text("import os; raise RuntimeError('must not execute')\n")
    assert collector["src_import_path"](tmp_path) == str(root)


@pytest.mark.parametrize("kind", ["missing", "file", "empty", "duplicate"])
def test_src_root_is_required_and_unambiguous(collector, tmp_path, kind):
    root = tmp_path / "src"
    if kind == "file":
        root.write_text("not a directory")
    elif kind != "missing":
        root.mkdir()
        if kind == "duplicate":
            (root / "owned_duplicate.py").write_text("")
            (root / "owned_duplicate").mkdir()
    with pytest.raises(ValueError):
        collector["src_import_path"](tmp_path)


@pytest.mark.parametrize("name", ["packaging", "pytest", "json", "sys"])
def test_image_or_stdlib_module_collisions_refuse_without_import(collector, tmp_path, name):
    root = tmp_path / "src"
    root.mkdir()
    (root / f"{name}.py").write_text("raise RuntimeError('must not import')\n")
    with pytest.raises(ValueError, match="collides"):
        collector["src_import_path"](tmp_path)


def test_loaded_module_without_spec_is_rejected(collector, tmp_path, monkeypatch):
    import sys

    root = tmp_path / "src"
    root.mkdir()
    (root / "owned_loaded_without_spec.py").write_text("")
    monkeypatch.setitem(sys.modules, "owned_loaded_without_spec", object())
    with pytest.raises(ValueError, match="collides"):
        collector["src_import_path"](tmp_path)


@pytest.mark.parametrize("kind", ["module", "package", "namespace"])
def test_root_workspace_cannot_shadow_src(collector, tmp_path, kind):
    root = tmp_path / "src"
    root.mkdir()
    (root / "owned_collision.py").write_text("")
    if kind == "module":
        (tmp_path / "owned_collision.py").write_text("")
    else:
        (tmp_path / "owned_collision").mkdir()
        if kind == "package":
            (tmp_path / "owned_collision/__init__.py").write_text("")
    with pytest.raises(ValueError, match="collides"):
        collector["src_import_path"](tmp_path)


@pytest.mark.parametrize("kind", ["root", "child", "workspace"])
def test_symlinks_are_not_src_roots_or_children(collector, tmp_path, kind):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "owned_symlink.py").write_text("")
    try:
        if kind == "workspace":
            (target / "src").mkdir()
            (target / "src/owned_symlink.py").write_text("")
            workspace = tmp_path / "alias"
            workspace.symlink_to(target, target_is_directory=True)
        elif kind == "root":
            (workspace / "src").symlink_to(target, target_is_directory=True)
        else:
            (workspace / "src").mkdir()
            (workspace / "src/alias").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Host cannot create symlinks; Linux Docker case covers this boundary")
    with pytest.raises(ValueError):
        collector["src_import_path"](workspace)


@pytest.fixture
def src_runner():
    image = os.environ.get("TEST_SRC_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SRC_SANDBOX_IMAGE is not configured")
    return DockerRunner(image)


async def src_check(runner, root, files, *, directive=True):
    artifacts = ArtifactStore(root)
    argv = (*PREFIX, *(DIRECTIVE if directive else ()), NODE)
    command = CommandProfile(id="owned-src", argv=argv)
    result = await verify(
        files,
        (command,),
        runner,
        artifacts,
        timeout=20,
        workflow_id="owned-src-profile",
    )
    receipt = json.loads(artifacts.get(result["commands"][0]["artifact_digest"]))
    return result, receipt


def owned_files(prefix="src/"):
    return {
        f"{prefix}owned_application/__init__.py": "VALUE = 7\n",
        "tests/test_owned.py": (
            "import unittest\n"
            "import pytest\n"
            "import owned_application\n"
            "class TestOwned(unittest.TestCase):\n"
            "    def test_origin(self):\n"
            f"        assert owned_application.__file__ == '/workspace/{prefix}"
            "owned_application/__init__.py'\n"
            "        assert owned_application.VALUE == 7\n"
            "        assert pytest.__file__.startswith('/usr/local/lib/')\n"
        ),
        "conftest.py": "raise RuntimeError('repository conftest must not load')\n",
        "pytest.ini": "[pytest]\npythonpath = nonexistent\naddopts = --invalid\n",
    }


@pytest.mark.integration
@pytest.mark.parametrize("layout", ["src", "flat"])
async def test_actual_src_and_flat_package_origins(src_runner, tmp_path, layout):
    directive = layout == "src"
    result, receipt = await src_check(
        src_runner,
        tmp_path,
        owned_files("" if layout == "flat" else "src/"),
        directive=directive,
    )
    assert result["passed"], receipt["stderr"]
    assert receipt["collector_profile"] == "image-owned-pytest-v1"
    assert receipt["verification_report"]["collector_version"] == 1
    assert receipt["verification_report"]["collected"] == [NODE]
    assert set(receipt["verification_binding"]) == {
        "nonce",
        "snapshot_digest",
        "command_digest",
        "argv",
    }


@pytest.mark.integration
async def test_actual_src_is_not_enabled_implicitly(src_runner, tmp_path):
    result, receipt = await src_check(src_runner, tmp_path, owned_files(), directive=False)
    assert not result["passed"]
    assert receipt["verification_report"]["collection_errors"]


@pytest.mark.integration
@pytest.mark.parametrize("name", ["packaging", "pytest", "json", "sys", "owned_application"])
async def test_actual_import_collisions_refuse_before_test_code(src_runner, tmp_path, name):
    files = owned_files()
    if name == "owned_application":
        files["owned_application/__init__.py"] = "raise RuntimeError('must not import')\n"
    else:
        files[f"src/{name}.py"] = "raise RuntimeError('must not import')\n"
    result, receipt = await src_check(src_runner, tmp_path, files)
    assert not result["passed"]
    assert receipt["verification_report"] is None
    assert "Src module collides" in receipt["stderr"]
    assert "must not import" not in receipt["stderr"]


@pytest.mark.integration
async def test_actual_missing_src_refuses_before_collection(src_runner, tmp_path):
    result, receipt = await src_check(src_runner, tmp_path, owned_files(""))
    assert not result["passed"]
    assert receipt["verification_report"] is None
    assert "Missing or unsafe src import root" in receipt["stderr"]


@pytest.mark.integration
async def test_actual_src_behavior_call_fails_then_passes_with_unchanged_regression(
    src_runner, tmp_path
):
    """Owned four-run control, not a historical twelve-run qualification claim."""
    oracle_path = "__delivery_oracle__/test_owned_behavior.py"
    acceptance_node = oracle_path + "::TestBehavior::test_requested"
    regression_node = "tests/test_original.py::test_original"
    original_test = (
        "from owned_behavior import value\ndef test_original():\n    assert value() >= 1\n"
    )
    baseline = {
        "src/owned_behavior.py": "def value(): return 1\n",
        "tests/test_original.py": original_test,
        oracle_path: (
            "import unittest\n"
            "import owned_behavior\n"
            "class TestBehavior(unittest.TestCase):\n"
            "    def test_requested(self):\n"
            "        assert owned_behavior.__file__ == '/workspace/src/owned_behavior.py'\n"
            "        assert owned_behavior.value() == 2\n"
        ),
    }
    reference = {**baseline, "src/owned_behavior.py": "def value(): return 2\n"}
    artifacts = ArtifactStore(tmp_path)
    for variant, snapshot in (("baseline", baseline), ("reference", reference)):
        assert snapshot["tests/test_original.py"] == original_test
        for suite, node in (("acceptance", acceptance_node), ("regression", regression_node)):
            command = CommandProfile(id=suite, argv=(*PREFIX, *DIRECTIVE, node))
            result = await verify(
                snapshot,
                (command,),
                src_runner,
                artifacts,
                timeout=20,
                workflow_id=f"owned-src-{variant}-{suite}",
            )
            receipt = json.loads(artifacts.get(result["commands"][0]["artifact_digest"]))
            expected_failure = variant == "baseline" and suite == "acceptance"
            assert result["passed"] is not expected_failure
            assert receipt["exit_code"] == (1 if expected_failure else 0)
            assert receipt["image"] == src_runner.image
            assert receipt["verification_binding"]["argv"] == list(command.argv)
            report = receipt["verification_report"]
            assert report["collected"] == [node]
            assert report["collection_errors"] == [] and report["deselected"] == []
            assert [(phase["when"], phase["outcome"]) for phase in report["phases"]] == [
                ("setup", "passed"),
                ("call", "failed" if expected_failure else "passed"),
                ("teardown", "passed"),
            ]


@pytest.mark.integration
async def test_actual_linux_src_symlink_refuses(src_runner):
    # The snapshot transport correctly cannot create links. This owned in-container
    # probe additionally exercises the collector's direct-use check on a Linux link.
    script = (
        "import runpy\n"
        "from pathlib import Path\n"
        "workspace = Path('/workspace')\n"
        "(workspace / 'target').mkdir()\n"
        "(workspace / 'src').symlink_to(workspace / 'target', target_is_directory=True)\n"
        "check = runpy.run_path('/opt/delivery/collector.py')['src_import_path']\n"
        "try:\n"
        "    check(workspace)\n"
        "except ValueError:\n"
        "    print('owned symlink refused')\n"
        "else:\n"
        "    raise AssertionError('unsafe src accepted')\n"
    )
    receipt = await src_runner.run({}, ("python", "-I", "-c", script), timeout_seconds=20)
    assert receipt.exit_code == 0, receipt.stderr
    assert receipt.stdout.strip() == "owned symlink refused"
