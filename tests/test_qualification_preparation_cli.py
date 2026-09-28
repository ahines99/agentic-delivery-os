"""Offline protected preparation through the public CLI; synthetic inputs only."""

import json
import os
import subprocess
import sys
from datetime import datetime

import pytest
from test_qualification_preparation import LICENSE, NOW, synthetic

from agentic_delivery.evaluation import cli
from agentic_delivery.evaluation.qualification_preparation import PreparationRequest
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.fixture
def command(tmp_path, monkeypatch):
    request, kwargs, task = synthetic.__wrapped__(tmp_path)()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    config_path = inputs / "config.json"
    request_path = inputs / "request.json"
    policy_path = inputs / "policy.json"
    for path, contract in (
        (config_path, kwargs["settings"]),
        (request_path, request),
        (policy_path, kwargs["policy"]),
    ):
        path.write_text(contract.model_dump_json(), encoding="utf-8")
    summary = tmp_path / "summary.json"
    options = {
        "config": config_path,
        "request": request_path,
        "policy": policy_path,
        "artifacts": kwargs["protected_artifacts"].root,
        "output-artifacts": kwargs["output_root"],
        "worker-root": kwargs["worker_root"],
        "output": summary,
    }

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(cli, "datetime", FrozenClock)

    def arguments(**updates):
        return [
            "prepare-qualification",
            *[
                part
                for name, value in {**options, **updates}.items()
                for part in ("--" + name, str(value))
            ],
        ]

    return options, arguments, task


def test_cli_only_writes_new_metadata_and_never_executes_or_qualifies(command, monkeypatch, capsys):
    options, arguments, task = command
    from agentic_delivery.execution.docker import DockerRunner
    from agentic_delivery.integrations.model import StructuredModel

    async def forbidden(*args, **kwargs):
        raise AssertionError("Preparation cannot execute models or Docker")

    def no_artifacts(*args, **kwargs):
        raise AssertionError("Preparation must not write qualification artifacts")

    monkeypatch.setattr(StructuredModel, "generate", forbidden)
    monkeypatch.setattr(DockerRunner, "preflight", forbidden)
    monkeypatch.setattr(DockerRunner, "run", forbidden)
    monkeypatch.setattr(ArtifactStore, "put", no_artifacts)
    root = options["output"].parent
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert cli.main(arguments()) == 0
    summary = json.loads(options["output"].read_bytes())
    assert summary["task_id"] == task["id"]
    assert summary["status"] == "PREPARED_NOT_QUALIFIED"
    assert summary["execution_authorized"] is False and summary["admitted"] is False
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert {p for p in root.rglob("*") if p.is_file()} == set(before) | {options["output"]}
    rendered = options["output"].read_text() + capsys.readouterr().out
    for forbidden_text in ("VALUE =", "test_value", "test_existing", LICENSE):
        assert forbidden_text not in rendered


@pytest.mark.parametrize("scope", ["artifacts", "output-artifacts", "worker-root"])
def test_cli_output_cannot_enter_any_protected_execution_scope(command, scope):
    options, arguments, _ = command
    output = options[scope] / "summary.json"
    with pytest.raises(SystemExit) as failure:
        cli.main(arguments(output=output))
    assert failure.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("input_name", ["config", "request", "policy", "output"])
def test_cli_never_overwrites_inputs_or_an_existing_summary(command, input_name):
    options, arguments, _ = command
    destination = options[input_name]
    if input_name == "output":
        destination.write_bytes(b"existing report must survive")
    before = destination.read_bytes()
    with pytest.raises(SystemExit):
        cli.main(arguments(output=destination))
    assert destination.read_bytes() == before


@pytest.mark.parametrize("scope", ["artifacts", "output-artifacts", "worker-root"])
def test_missing_scope_is_not_created_by_artifact_store_constructor(command, scope):
    options, arguments, _ = command
    absent = options["output"].parent / "absent"
    with pytest.raises(SystemExit):
        cli.main(arguments(**{scope: absent}))
    assert not absent.exists() and not options["output"].exists()


@pytest.mark.parametrize("malformed", ["duplicate", "nonfinite", "schema", "oversize"])
def test_cli_invalid_private_document_is_refused_without_echo(command, malformed, capsys):
    options, arguments, _ = command
    canary = "PRIVATE_PREPARATION_INPUT_CANARY"
    contents = {
        "duplicate": '{"schema_version":1,"schema_version":1,"private":"' + canary + '"}',
        "nonfinite": '{"schema_version":NaN,"private":"' + canary + '"}',
        "schema": json.dumps({"schema_version": canary}),
        "oversize": canary + "x" * (4 * 1024 * 1024),
    }[malformed]
    options["request"].write_text(contents, encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        cli.main(arguments())
    assert failure.value.code == 2
    messages = capsys.readouterr()
    assert canary not in messages.out + messages.err
    assert "inspect protected inputs privately" in messages.err
    assert not options["output"].exists()


@pytest.mark.parametrize(
    "kind",
    [
        "preparation-request",
        "preparation-policy",
        "license-evidence",
        "usage-authorization",
        "reference-provenance",
    ],
)
def test_cli_exports_preparation_contracts(tmp_path, kind):
    path = tmp_path / "schema.json"
    assert cli.main(["schema", "--kind", kind, "--output", str(path)]) == 0
    assert json.loads(path.read_bytes())["additionalProperties"] is False


def test_document_reader_refuses_posix_fifo_without_blocking(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO is unavailable on Windows")
    fifo = tmp_path / "request.json"
    os.mkfifo(fifo)
    source = (
        "from pathlib import Path\n"
        "from agentic_delivery.evaluation.cli import read_preparation_document\n"
        "from agentic_delivery.evaluation.qualification_preparation import PreparationRequest\n"
        "import sys\n"
        "try:\n"
        "    read_preparation_document(Path(sys.argv[1]), PreparationRequest)\n"
        "except ValueError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('FIFO unexpectedly accepted')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source, str(fifo)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


def test_document_reader_refuses_directory(tmp_path):
    with pytest.raises((OSError, ValueError)):
        cli.read_preparation_document(tmp_path, PreparationRequest)
