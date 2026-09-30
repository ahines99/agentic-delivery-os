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
