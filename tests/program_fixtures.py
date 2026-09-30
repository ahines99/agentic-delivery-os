"""Explicit owned-test program enrollment; never a production permission or registry lookup."""

from pathlib import Path

from sqlalchemy.engine import make_url

from agentic_delivery.evaluation.campaign_allocation import configured_ledger_identity
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.program_budget import ProgramBudgetPolicy, ProgramBudgetRegistry


def program_ledger(url: str, *, registry_path: Path | None = None) -> EvaluationExecutionStore:
    target = configured_ledger_identity(url)
    if registry_path is None:
        parsed = make_url(url)
        assert parsed.get_backend_name() == "sqlite" and parsed.database is not None
        ledger_path = Path(parsed.database)
        registry_path = ledger_path.with_name(
            "delivery_eval_program_" + ledger_path.stem + ".sqlite"
        )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    policy = ProgramBudgetPolicy(
        program_id="owned-test-program",
        authorization_digest="a" * 64,
        cap_microdollars=1_000_000_000,
        approved_ledger_identities=(target,),
    )
    if registry_path.exists():
        registry = ProgramBudgetRegistry(registry_path, current_guard=lambda: None)
        assert registry.snapshot().policy == policy
    else:
        registry = ProgramBudgetRegistry.create(registry_path, policy, current_guard=lambda: None)
    return EvaluationExecutionStore(url, program_budget=registry)


def discard_owned_fixture_allocation(store: EvaluationExecutionStore, account_id: str) -> None:
    """Remove only an unused test scaffold before exercising real first allocation.

    This is fixture construction, not a production closure/recovery operation. Never call
    with a live account. The original candidate fixture computes terms from an allocation;
    dispatcher tests need the same owned terms before their prospective journal is frozen.
    """
    import sqlite3

    from sqlalchemy import delete, select

    from agentic_delivery.evaluation.campaign_allocation import ALLOCATION_CHECKPOINT
    from agentic_delivery.evaluation.campaign_scoring import ATTEMPT_CHECKPOINT
    from agentic_delivery.evaluation.execution_store import (
        accounts,
        checkpoints,
        operations,
        program_account_states,
    )

    registry = store.program_budget
    assert registry is not None and registry.snapshot().policy.program_id == "owned-test-program"
    assert account_id.startswith("campaign:")
    account = store.account(account_id)
    assert all(
        account[k] == 0
        for k in ("spent_microdollars", "reserved_microdollars", "input_tokens", "output_tokens")
    )
    envelope = next(e for e in registry.snapshot().envelopes if e.account_id == account_id)
    assert envelope.state == "ACTIVE" and envelope.closed_microdollars is None
    with store.engine.begin() as connection:
        assert (
            connection.scalar(select(operations.c.id).where(operations.c.account_id == account_id))
            is None
        )
        stages = set(
            connection.scalars(
                select(checkpoints.c.stage).where(checkpoints.c.account_id == account_id)
            )
        )
        assert stages == {ATTEMPT_CHECKPOINT, ALLOCATION_CHECKPOINT}
        assert connection.execute(
            select(program_account_states).where(program_account_states.c.account_id == account_id)
        ).one() == (account_id, "OPEN", None)
        connection.execute(delete(checkpoints).where(checkpoints.c.account_id == account_id))
        connection.execute(
            delete(program_account_states).where(program_account_states.c.account_id == account_id)
        )
        connection.execute(delete(accounts).where(accounts.c.id == account_id))
    with sqlite3.connect(registry.path) as connection:
        assert (
            connection.execute(
                "DELETE FROM envelopes WHERE account=? AND state='ACTIVE'", (account_id,)
            ).rowcount
            == 1
        )
