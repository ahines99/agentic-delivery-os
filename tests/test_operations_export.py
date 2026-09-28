import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.operations import export as export_module
from agentic_delivery.operations.export import export_metadata, main, safe_destination
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CIHeadRecord, CommandRecord, UsageRecord, WorkRecord
from agentic_delivery.storage.store import Store, now_iso

CANARY = "SECRET-CANARY-provider-token-private-description-stdout-stderr"


@pytest.fixture
def configured(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'state.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        repositories=(
            RepositoryConfig(
                id="demo/customer-service",
                github_owner="demo",
                github_name="customer-service",
                github_repository_id=123,
            ),
        ),
    )
    settings.artifact_root.mkdir()
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex, "title": CANARY, "description": CANARY})
    receipt = store.submit(
        item, actor=CANARY, key=CANARY, budget=Budget(), configuration_digest="f" * 64
    )
    identity = receipt["workflow_id"]
    store.project(
        identity,
        1,
        "INGESTED",
        actor=CANARY,
        reason=CANARY,
        spec_digest=store.workflow(identity)["spec_digest"],
        result={
            "manifest_digest": "a" * 64,
            "stdout": CANARY,
            "ci": {"evidence_digest": "b" * 64, "provider": CANARY},
        },
    )
    store.reserve(identity, identity + ":build:1", 100, 50, 10)
    store.reserve(identity, identity + ":review:1", 200, 50, 10)
    store.settle(
        identity + ":build:1",
        cost=90,
        input_tokens=5,
        output_tokens=2,
        result={"output": CANARY, "provider_id": CANARY, "model": CANARY},
    )
    store.save_publication(
        identity,
        item.repository,
        {
            "number": 7,
            "base_sha": "c" * 40,
            "head_sha": "d" * 40,
            "manifest_digest": "a" * 64,
            "provider_token": CANARY,
        },
    )
    with Session(store.engine) as session, session.begin():
        command = session.get(CommandRecord, receipt["command_id"])
        assert command
        command.reason = CANARY
        session.add(
            CIHeadRecord(
                repository_id=123,
                head_sha="d" * 40,
                generation=2,
                snapshot_generation=2,
                policy_digest="f" * 64,
                evidence_digest="b" * 64,
                snapshot=[{"provider_response": CANARY}],
                observed_at=now_iso(),
                reconciled_at=now_iso(),
                expires_at=now_iso(),
                invalidation_reason=CANARY,
            )
        )
    config = tmp_path / "operator-settings.json"
    config.write_text(settings.model_dump_json())
    return settings, store, identity, config


def test_allowlisted_export_excludes_canaries_and_preserves_unknown_reservations(
    configured,
) -> None:
    settings, store, identity, _ = configured
    before = store.workflow(identity)
    report = export_metadata(settings, identity)
    serialized = json.dumps(report)
    assert CANARY not in serialized
    assert "provider_token" not in serialized
    assert "database_url" not in serialized
    assert "actor" not in serialized and "payload" not in serialized and "reason" not in serialized
    assert report["schema_version"] == 1
    assert report["workflow"]["workflow_id"] == identity
    assert report["workflow"]["manifest_digest"] == "a" * 64
    assert report["workflow"]["configuration_digest"] == "f" * 64
    assert report["ci"]["evidence_digest"] == "b" * 64
    assert report["publication"]["base_sha"] == "c" * 40
    assert report["unknown_model_operations"] == 1
    operations = {row["operation_id"]: row for row in report["model_operations"]}
    assert operations[identity + ":review:1"]["outcome"] == "UNKNOWN"
    assert operations[identity + ":review:1"]["actual_microdollars"] is None
    assert operations[identity + ":build:1"]["actual_microdollars"] == 90
    assert store.workflow(identity) == before
    with Session(store.engine) as session:
        assert session.get(UsageRecord, identity + ":build:1").result["output"] == CANARY


def test_export_reads_only_selected_workflow(configured) -> None:
    settings, store, identity, _ = configured
    with Session(store.engine) as session:
        original = session.scalar(select(WorkRecord))
        item = WorkItem.model_validate(original.payload).model_copy(update={"id": uuid4().hex})
    second = store.submit(item, actor="other", key=uuid4().hex, budget=Budget())["workflow_id"]
    store.reserve(second, second + ":build:1", 333, 20, 10)
    assert second not in json.dumps(export_metadata(settings, identity))


def test_cli_exclusively_creates_and_never_overwrites(configured, tmp_path: Path, capsys) -> None:
    settings, _, identity, config = configured
    destination = tmp_path / "export.json"
    args = ["--config", str(config), "--workflow-id", identity, "--output", str(destination)]
    assert main(args) == 0
    before = destination.read_bytes()
    assert CANARY not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(args)
    assert destination.read_bytes() == before
    assert CANARY not in capsys.readouterr().err
    assert (
        safe_destination(tmp_path / "another.json", config, settings) == tmp_path / "another.json"
    )


@pytest.mark.parametrize("target", ["config", "artifact", "source", "private-name", "non-json"])
def test_protected_destinations_rejected(configured, target: str, tmp_path: Path) -> None:
    settings, _, _, config = configured
    paths = {
        "config": config,
        "artifact": settings.artifact_root / "export.json",
        "source": Path(__file__).resolve().parent / "new-export.json",
        "private-name": tmp_path / "config.local.json",
        "non-json": tmp_path / "export.py",
    }
    before = config.read_bytes()
    with pytest.raises(ValueError):
        safe_destination(paths[target], config, settings)
    assert config.read_bytes() == before


def test_symlink_destination_cannot_follow_into_artifacts(configured, tmp_path: Path) -> None:
    settings, _, _, config = configured
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(settings.artifact_root, target_is_directory=True)
    except OSError:
        pytest.skip("Platform does not permit unprivileged symlink creation")
    with pytest.raises(ValueError):
        safe_destination(alias / "export.json", config, settings)


def test_cli_errors_do_not_print_private_config_or_missing_workflow(
    configured, tmp_path: Path, capsys
) -> None:
    _, _, _, config = configured
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(config),
                "--workflow-id",
                CANARY,
                "--output",
                str(tmp_path / "export.json"),
            ]
        )
    error = capsys.readouterr().err
    assert CANARY not in error
    assert "sqlite" not in error
    assert not (tmp_path / "export.json").exists()


def test_row_limit_fails_without_truncated_output(configured, tmp_path: Path, monkeypatch) -> None:
    _, _, identity, config = configured
    monkeypatch.setattr(export_module, "MAX_ROWS", 0)
    output = tmp_path / "bounded.json"
    with pytest.raises(SystemExit):
        main(["--config", str(config), "--workflow-id", identity, "--output", str(output)])
    assert not output.exists()


def test_unonboarded_repository_is_not_exported(configured) -> None:
    settings, _, identity, _ = configured
    with pytest.raises(ValueError, match="not onboarded"):
        export_metadata(settings.model_copy(update={"repositories": ()}), identity)
