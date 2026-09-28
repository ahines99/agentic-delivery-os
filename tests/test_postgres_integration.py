import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import WorkItem
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
