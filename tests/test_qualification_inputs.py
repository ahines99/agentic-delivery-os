"""Runtime-ledger input assembly; fixture history is synthetic test data only."""

from datetime import UTC, datetime

import pytest
from test_qualification_preparation import synthetic  # noqa: F401
from test_qualification_runtime import controlled, setup  # noqa: F401

from agentic_delivery.evaluation.qualification import EvidenceSummary, QualificationInput
from agentic_delivery.evaluation.qualification_inputs import (
    ELIGIBILITY,
    InputMaterializationFailure,
    materialize_qualification_input,
)
from agentic_delivery.evaluation.qualification_runtime import run_deterministic_qualification


@pytest.fixture
async def completed(setup, controlled):  # noqa: F811
    request, options, state = setup(actual_clock=True)
    options["clock"] = lambda: datetime.now(UTC)
    result = await run_deterministic_qualification(request, **options)
    store = options["protected_artifacts"]
    support = store.put(b"Controlled preliminary findings, never historical admission evidence.")
    arguments = {
        key: options[key]
        for key in ("protected_artifacts", "output_artifacts", "worker_root", "ledger")
    }
    arguments.update(
        authorization=state["authorization"],
        settings=state["settings"],
        policy=state["policy"],
        now=datetime.now(UTC),
        check_evidence=dict.fromkeys(ELIGIBILITY, support),
        findings=tuple(
            EvidenceSummary(
                check=check,
                status="PENDING",
                summary="Preliminary fixture evidence; semantic review has not occurred.",
                evidence_refs=(support,),
            )
            for check in sorted(ELIGIBILITY)
        ),
    )
    return request, result["evidence_artifact"], arguments, controlled


async def test_completed_input_reconstructs_exact_receipts_without_new_effects(completed):
    request, evidence, args, runner = completed
    ledger = args["ledger"]
    account = ledger.account(args["authorization"].account_id)
    reference = materialize_qualification_input(request, evidence, **args)
    assert materialize_qualification_input(request, evidence, **args) == reference
    spec = QualificationInput.model_validate_json(args["protected_artifacts"].get(reference))
    assert len(spec.executions) == 12 and set(spec.checks.model_dump().values()) == {"PENDING"}
    assert runner.calls == 12 and runner.preflights == 1
    assert ledger.account(args["authorization"].account_id) == account
    for execution in spec.executions:
        assert args["protected_artifacts"].get(execution.receipt_artifact) == args[
            "output_artifacts"
        ].get(execution.receipt_artifact)
    assert (
        ledger.checkpoint_receipt(args["authorization"].account_id, "runtime-review-input-v1")[
            "artifact_digest"
        ]
        == reference
    )


@pytest.mark.parametrize("fault", ["checkpoint", "unknown", "authority", "finding", "evidence"])
async def test_unverified_inputs_never_materialize(completed, monkeypatch, fault):
    request, evidence, args, runner = completed
    ledger = args["ledger"]
    if fault == "checkpoint":
        monkeypatch.setattr(ledger, "checkpoint_receipt", lambda *a: None)
    elif fault == "unknown":
        original = ledger.operation_receipt

        def changed(*a):
            row = original(*a)
            row["status"] = "RESERVED"
            return row

        monkeypatch.setattr(ledger, "operation_receipt", changed)
    elif fault == "authority":
        args["settings"] = args["settings"].model_copy(update={"admissions_enabled": False})
    elif fault == "finding":
        args["findings"] = args["findings"][:-1]
    else:
        evidence = "0" * 64
    with pytest.raises(InputMaterializationFailure, match="Completed runtime"):
        materialize_qualification_input(request, evidence, **args)
    assert runner.calls == 12


async def test_materialized_findings_cannot_change_on_resume(completed):
    request, evidence, args, _ = completed
    reference = materialize_qualification_input(request, evidence, **args)
    args["findings"] = tuple(f.model_copy(update={"status": "PASS"}) for f in args["findings"])
    with pytest.raises(InputMaterializationFailure):
        materialize_qualification_input(request, evidence, **args)
    checkpoint = args["ledger"].checkpoint_receipt(
        args["authorization"].account_id, "runtime-review-input-v1"
    )
    assert checkpoint["artifact_digest"] == reference
