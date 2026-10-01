"""Read-only reachability plans never grant deletion authority."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.operations import retention
from agentic_delivery.operations.retention import RetentionFailure, RetentionRequest, plan_retention
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord, OutboxRecord, RunRecord, UsageRecord
from agentic_delivery.storage.store import Store

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
CANARY = "PRIVATE-SOURCE-PROVIDER-TOKEN-CANARY"


def request(**changes):
    return RetentionRequest(
        **{
            "retention_days": 30,
            "dedicated_control_plane_store": True,
            "writers_quiescent": True,
            "external_roots_complete": True,
            "backups_independent": True,
            **changes,
        }
    )


@pytest.fixture
def configured(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'state.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        repositories=(
            RepositoryConfig(
                id="demo/customer-service", github_owner="demo", github_name="service"
            ),
        ),
    )
    return settings, ArtifactStore(settings.artifact_root), Store(create_database(url))


def artifact(store, content, *, age=60):
    raw = content if isinstance(content, bytes) else json.dumps(content).encode()
    digest = store.put(raw)
    stamp = (NOW - timedelta(days=age)).timestamp()
    os.utime(store.root / digest[:2] / digest, (stamp, stamp))
    return digest


def closed_workflow(store, result):
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    receipt = store.submit(item, actor=CANARY, key=CANARY, budget=Budget())
    with Session(store.engine) as session, session.begin():
        run = session.get(RunRecord, receipt["workflow_id"])
        run.state, run.result = "CANCELLED", result
        session.get(CommandRecord, receipt["command_id"]).status = "REJECTED"
        session.execute(update(OutboxRecord).values(delivered=True))
    return receipt["workflow_id"]


def rows(plan):
    return {row["digest"]: row for row in plan["artifacts"]}


def test_database_and_transitive_roots_preserved_with_no_raw_payload_or_mutation(configured):
    settings, artifacts, store = configured
    child = artifact(artifacts, {"source": CANARY})
    parent = artifact(artifacts, {"child": child})
    orphan = artifact(artifacts, b"old unreferenced bytes")
    closed_workflow(store, {"manifest_digest": parent, "private": CANARY})
    database = Path(store.engine.url.database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    plan = plan_retention(settings, request(), now=NOW)
    assert rows(plan)[parent]["reason"] == "database_reference"
    assert rows(plan)[child]["reason"] == "transitive_reference_from_retained_artifact"
    assert rows(plan)[orphan]["disposition"] == "CANDIDATE_REVIEW_ONLY"
    assert plan["counts"]["candidate_bytes"] == len(b"old unreferenced bytes")
    assert CANARY not in json.dumps(plan) and "database_url" not in json.dumps(plan)
    assert plan["deletion_authorized"] is False
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert artifacts.get(orphan) == b"old unreferenced bytes"
    assert plan_retention(settings, request(), now=NOW) == plan


def test_young_future_and_explicit_roots_keep_old_dependencies(configured):
    settings, artifacts, _ = configured
    child = artifact(artifacts, b"old child")
    young = artifact(artifacts, {"dependency": child}, age=1)
    future = artifact(artifacts, b"future", age=-1)
    held = artifact(artifacts, b"external legal hold")
    plan = plan_retention(settings, request(retained_roots=(held,)), now=NOW)
    assert plan["counts"]["candidate"] == 0
    assert rows(plan)[held]["reason"] == "explicit_retained_root"
    assert rows(plan)[child]["reason"] == "transitive_reference_from_retained_artifact"
    assert rows(plan)[young]["disposition"] == rows(plan)[future]["disposition"] == "KEEP"


def test_json_escaped_references_are_retained(configured):
    settings, artifacts, _ = configured
    child = artifact(artifacts, b"escaped child")
    encoded = '"' + "".join(f"\\u{ord(char):04x}" for char in child) + '"'
    parent = artifact(artifacts, encoded.encode())
    plan = plan_retention(settings, request(retained_roots=(parent,)), now=NOW)
    assert rows(plan)[child]["disposition"] == "KEEP"


@pytest.mark.parametrize("layers", [1, 3])
def test_nested_escaped_json_references_keep_old_children(configured, layers):
    settings, artifacts, _ = configured
    child = artifact(artifacts, b"nested escaped child")
    escaped = "".join(f"\\u{ord(char):04x}" for char in child)
    nested = '{"reference":"' + escaped + '"}'
    for _ in range(layers):
        nested = json.dumps({"metadata.json": nested})
    parent = artifact(artifacts, nested.encode())
    plan = plan_retention(settings, request(retained_roots=(parent,)), now=NOW)
    assert rows(plan)[parent]["disposition"] == "KEEP"
    assert rows(plan)[child]["reason"] == "transitive_reference_from_retained_artifact"
    assert plan["counts"]["candidate"] == 0


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_keys_refuse_before_discarding_escaped_reference(configured, nested):
    settings, artifacts, _ = configured
    child = artifact(artifacts, b"duplicate key child")
    escaped = "".join(f"\\u{ord(char):04x}" for char in child)
    content = '{"reference":"' + escaped + '","refere\\u006ece":"none"}'
    if nested:
        content = json.dumps({"metadata.json": content})
    parent = artifact(artifacts, content.encode())
    with pytest.raises(RetentionFailure, match="Duplicate artifact JSON key"):
        plan_retention(settings, request(retained_roots=(parent,)), now=NOW)


@pytest.mark.parametrize(
    "limit", ["MAX_REFERENCE_DEPTH", "MAX_REFERENCE_NODES", "MAX_REFERENCE_TEXT_BYTES"]
)
def test_reference_analysis_bounds_refuse_instead_of_underretaining(configured, monkeypatch, limit):
    settings, artifacts, _ = configured
    parent = artifact(artifacts, {"nested": json.dumps({"reference": "a" * 64})})
    monkeypatch.setattr(retention, limit, 1)
    with pytest.raises(RetentionFailure, match="reference .* limit exceeded"):
        plan_retention(settings, request(retained_roots=(parent,)), now=NOW)


@pytest.mark.parametrize(
    "age,expected", [(31, "CANDIDATE_REVIEW_ONLY"), (30, "KEEP"), (29, "KEEP")]
)
def test_age_cutoff_strict(configured, age, expected):
    settings, artifacts, _ = configured
    digest = artifact(artifacts, b"age boundary", age=age)
    assert rows(plan_retention(settings, request(), now=NOW))[digest]["disposition"] == expected
    assert artifacts.get(digest) == b"age boundary"


@pytest.mark.parametrize(
    "flag",
    [
        "dedicated_control_plane_store",
        "writers_quiescent",
        "external_roots_complete",
        "backups_independent",
    ],
)
def test_scope_required_before_io(configured, monkeypatch, flag):
    def forbidden(*args, **kwargs):
        pytest.fail("Unestablished scope reached database read")

    monkeypatch.setattr(retention, "database_snapshot", forbidden)
    with pytest.raises(RetentionFailure, match="Dedicated scope"):
        plan_retention(configured[0], request(**{flag: False}), now=NOW)


@pytest.mark.parametrize("state", ["NEW", "IMPLEMENTING", "HUMAN_REVIEW", "UNRECOGNIZED"])
def test_active_unknown_workflow_refuses(configured, state):
    settings, _, store = configured
    identity = closed_workflow(store, {})
    with Session(store.engine) as session, session.begin():
        session.get(RunRecord, identity).state = state
    with pytest.raises(RetentionFailure, match="workflow remains"):
        plan_retention(settings, request(), now=NOW)


@pytest.mark.parametrize("uncertainty", ["reservation", "outbox", "command", "tracker"])
def test_terminal_state_does_not_clear_unknown_operations(configured, uncertainty):
    settings, _, store = configured
    identity = closed_workflow(store, {})
    with Session(store.engine) as session, session.begin():
        if uncertainty == "reservation":
            session.add(
                UsageRecord(
                    id="unknown",
                    workflow_id=identity,
                    status="RESERVED",
                    reserved_microdollars=1,
                    reserved_input_tokens=1,
                    reserved_output_tokens=1,
                )
            )
        elif uncertainty == "outbox":
            session.execute(update(OutboxRecord).values(delivered=False))
        elif uncertainty == "command":
            session.execute(update(CommandRecord).values(status="RECEIVED"))
        else:
            session.get(RunRecord, identity).result = {"tracker_status": "UNKNOWN"}
    with pytest.raises(RetentionFailure):
        plan_retention(settings, request(), now=NOW)


@pytest.mark.parametrize(
    "defect", ["corrupt", "binary", "malformed_json", "foreign_entry", "hardlink"]
)
def test_unanalyzable_or_unsafe_store_refuses(configured, defect):
    settings, artifacts, _ = configured
    digest = artifact(artifacts, b"original")
    path = artifacts.root / digest[:2] / digest
    if defect == "corrupt":
        path.write_bytes(b"corrupt")
    elif defect == "binary":
        artifact(artifacts, b"\xff\x00")
    elif defect == "malformed_json":
        artifact(artifacts, b'{"reference": "\\u0061')
    elif defect == "foreign_entry":
        (artifacts.root / "backup-manifest.json").write_text("{}")
    else:
        os.link(path, artifacts.root.parent / "external-backup-link")
    with pytest.raises(RetentionFailure):
        plan_retention(settings, request(), now=NOW)


def test_symlink_refused(configured):
    settings, artifacts, _ = configured
    prefix = artifacts.root / "aa"
    prefix.mkdir()
    target = artifacts.root.parent / "outside"
    target.write_text("not evidence")
    try:
        (prefix / ("a" * 64)).symlink_to(target)
    except OSError:
        pytest.skip("Unprivileged symlink creation unavailable")
    with pytest.raises(RetentionFailure, match="link"):
        plan_retention(settings, request(), now=NOW)


def test_missing_hold_or_unknown_database_scope_refuses(configured):
    settings, _, store = configured
    with pytest.raises(RetentionFailure, match="root is absent"):
        plan_retention(settings, request(retained_roots=("f" * 64,)), now=NOW)
    with store.engine.begin() as connection:
        connection.execute(text("CREATE TABLE external_evaluator_refs (digest TEXT)"))
    with pytest.raises(RetentionFailure, match="table scope"):
        plan_retention(settings, request(), now=NOW)


def test_database_and_inventory_races_invalidate_plan(configured, monkeypatch):
    settings, artifacts, _ = configured
    artifact(artifacts, b"original")
    original_db, original_inventory = retention.database_snapshot, retention.inventory
    calls = 0

    def changing_database(current):
        nonlocal calls
        calls += 1
        result = original_db(current)
        if calls == 2:
            result["watermark"] = "0" * 64
        return result

    monkeypatch.setattr(retention, "database_snapshot", changing_database)
    with pytest.raises(RetentionFailure, match="Database changed"):
        plan_retention(settings, request(), now=NOW)
    monkeypatch.setattr(retention, "database_snapshot", original_db)
    calls = 0

    def changing_inventory(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            artifact(artifacts, b"new concurrent artifact")
        return original_inventory(root)

    monkeypatch.setattr(retention, "inventory", changing_inventory)
    with pytest.raises(RetentionFailure, match="inventory changed"):
        plan_retention(settings, request(), now=NOW)


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES"])
def test_artifact_bounds_refuse_instead_of_truncating(configured, monkeypatch, limit):
    settings, artifacts, _ = configured
    artifact(artifacts, b"nonempty artifact")
    monkeypatch.setattr(retention, limit, 0)
    with pytest.raises(RetentionFailure, match="limit exceeded"):
        plan_retention(settings, request(), now=NOW)


def test_database_bounds_refuse_instead_of_truncating(configured, monkeypatch):
    settings, _, store = configured
    closed_workflow(store, {})
    monkeypatch.setattr(retention, "MAX_TABLE_ROWS", 0)
    with pytest.raises(RetentionFailure, match="row limit"):
        plan_retention(settings, request(), now=NOW)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO is unavailable on Windows")
def test_fifo_refuses_without_blocking(tmp_path):
    import subprocess
    import sys

    prefix = tmp_path / "aa"
    prefix.mkdir()
    os.mkfifo(prefix / ("a" * 64))
    script = (
        "from pathlib import Path; import sys; "
        "from agentic_delivery.operations.retention import inventory, RetentionFailure\n"
        "try: inventory(Path(sys.argv[1]))\n"
        "except RetentionFailure: raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=10
    )
    assert result.returncode == 0


def test_cli_creates_metadata_only_and_refuses_overwrite(configured, tmp_path, capsys):
    settings, artifacts, _ = configured
    artifact(artifacts, CANARY.encode())
    config, output = tmp_path / "private-config.json", tmp_path / "plan.json"
    config.write_text(settings.model_dump_json())
    args = [
        "--config",
        str(config),
        "--output",
        str(output),
        "--retention-days",
        "30",
        "--dedicated-control-plane-store",
        "--writers-quiescent",
        "--external-roots-complete",
        "--backups-independent",
    ]
    assert retention.main(args) == 0
    assert CANARY not in output.read_text() + capsys.readouterr().out
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        retention.main(args)
    assert output.read_bytes() == before


@pytest.mark.integration
def test_postgres_disposable_database_readonly_consistent_plan(tmp_path, monkeypatch):
    configured_url = os.environ.get("TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("TEST_DATABASE_URL required for isolated PostgreSQL drill")
    base_url = make_url(configured_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL required")
    name = "delivery_retention_" + uuid4().hex
    assert re.fullmatch(r"delivery_retention_[a-f0-9]{32}", name)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    created = False
    store = None
    try:
        with admin.connect() as connection:
            assert not connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        isolated_url = base_url.set(database=name).render_as_string(hide_password=False)
        upgrade(isolated_url)
        settings = Settings(
            database_url=isolated_url,
            artifact_root=tmp_path / "isolated-artifacts",
            repositories=(
                RepositoryConfig(
                    id="demo/customer-service", github_owner="demo", github_name="service"
                ),
            ),
        )
        artifacts = ArtifactStore(settings.artifact_root)
        store = Store(create_database(isolated_url))
        child = artifact(artifacts, b"synthetic retained child")
        parent = artifact(artifacts, {"child": child})
        orphan = artifact(artifacts, b"synthetic review-only candidate")
        identity = closed_workflow(store, {"manifest_digest": parent})
        before = store.workflow(identity)
        transaction_modes = []
        original = retention._database_snapshot

        def verify_transaction(connection, current_settings):
            transaction_modes.append(
                (
                    connection.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                    connection.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                )
            )
            return original(connection, current_settings)

        monkeypatch.setattr(retention, "_database_snapshot", verify_transaction)
        plan = plan_retention(settings, request(), now=NOW)
        assert transaction_modes == [("on", "repeatable read")] * 2
        assert plan["counts"]["keep"] == 2 and plan["counts"]["candidate"] == 1
        assert rows(plan)[parent]["reason"] == "database_reference"
        assert rows(plan)[child]["reason"] == "transitive_reference_from_retained_artifact"
        assert rows(plan)[orphan]["disposition"] == "CANDIDATE_REVIEW_ONLY"
        assert artifacts.get(orphan) == b"synthetic review-only candidate"
        assert store.workflow(identity) == before
    finally:
        if store:
            store.engine.dispose()
        try:
            if created:
                assert re.fullmatch(r"delivery_retention_[a-f0-9]{32}", name)
                assert name != base_url.database
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}"')
                    assert not connection.scalar(
                        text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                    )
        finally:
            admin.dispose()
