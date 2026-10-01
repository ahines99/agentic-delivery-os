import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.checks import (
    RequiredCheck,
    parse_check_run,
    parse_check_run_response,
)
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import BudgetExceeded, Store


@pytest.mark.integration
def test_postgres_atomic_concurrent_budget_and_intake() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL PostgreSQL is not configured")
    upgrade(url)
    store = Store(create_database(url))
    task = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    task = task.model_copy(update={"id": uuid4().hex})
    key = uuid4().hex

    def send(_: int) -> str:
        return str(store.submit(task, actor="pg-test", key=key, budget=Budget())["workflow_id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(send, range(8)))
    assert len(set(identities)) == 1
    identity = identities[0]

    def reserve(number: int) -> bool:
        try:
            store.reserve(identity, f"{identity}:{number}", 3_000_000, 100, 100)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1
    assert store.workflow(identity)["reserved_microdollars"] == 3_000_000


@pytest.mark.integration
def test_postgres_ci_generation_concurrent_delivery_and_reconciliation() -> None:
    from test_ci_persistence import event, inbox

    url = os.environ.get("TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL PostgreSQL is not configured")
    upgrade(url)
    store = Store(create_database(url))
    head = uuid4().hex + uuid4().hex[:8]
    payload = event(head_sha=head)
    observation = parse_check_run(payload, repository_id=42, installation_id=17)

    def deliver(_: int) -> dict:
        return store.record_check_observation(observation, inbox(payload, uuid4().hex))

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(deliver, range(8)))
    assert sum(not receipt["duplicate"] for receipt in receipts) == 1
    assert store.ci_generation(42, head) == 1
    snapshot = (parse_check_run_response(payload["check_run"], repository_id=42),)

    def reconcile(_: int) -> bool:
        return store.save_ci_reconciliation(
            repository_id=42,
            head_sha=head,
            expected_generation=1,
            policy_digest="d" * 64,
            evidence_digest="e" * 64,
            observations=snapshot,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reconcile, range(8))) == 1
    parameters = {
        "repository_id": 42,
        "head_sha": head,
        "required": (RequiredCheck(name="quality", app_id=123),),
        "policy_digest": "d" * 64,
    }
    assert store.ci_readiness(**parameters)["ready"]
    payload["action"] = "rerequested"
    store.record_check_observation(
        parse_check_run(payload, repository_id=42, installation_id=17),
        inbox(payload, uuid4().hex),
    )
    assert not store.ci_readiness(**parameters)["ready"]
    assert store.ci_generation(42, head) == 3
    assert not reconcile(0)
