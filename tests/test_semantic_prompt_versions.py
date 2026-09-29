"""Version preservation and controlled broker wiring; no live-model accuracy claims."""

# ruff: noqa: F811
import hashlib
import json

import httpx
import pytest
from test_semantic_calibration import build, run, validate  # noqa: F401
from test_semantic_execution import (  # noqa: F401
    campaign_scoring,
    campaign_seed,
    controlled_scoring,
    executed,
    structural,
)
from test_semantic_preparation import setup  # noqa: F401

from agentic_delivery.evaluation import semantic_calibration as calibration
from agentic_delivery.evaluation import semantic_execution as execution
from agentic_delivery.integrations.model import forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.store import digest_json


def pin_calibration_prompt(case, prompt):
    reference = case.artifacts.put(prompt)
    case.spec = case.spec.model_copy(update={"prompt_artifact": reference})
    case.spec_ref = calibration._put(case.artifacts, case.spec)
    case.state["grant"] = case.state["grant"].model_copy(update={"spec_artifact": case.spec_ref})
    case.state["policy"] = case.state["policy"].model_copy(
        update={"approved_spec_artifacts": (case.spec_ref,)}
    )


def test_v1_golden_bytes_and_existing_serialized_schemas_unchanged():
    # These digests were captured from the original f61b71f worktree before this change.
    assert (
        hashlib.sha256(calibration.semantic_prompt("Frozen rubric \u03a9\n").encode()).hexdigest()
        == "66ebdbaedfd038c11bfcddce3c0ab93466d020a6a6663a9c936eecf6f03cb4b6"
    )
    assert (
        digest_json(calibration.SemanticCalibrationSpec.model_json_schema())
        == "23e6b80164a37d3db163abb5389b1ee76fd26cca372f4d9b30965530f1cece2f"
    )
    assert (
        digest_json(calibration.SemanticCalibrationAuthorization.model_json_schema())
        == "c94a7063d403a25f53a37d6ee6aaf8ba82127f2ecb50db7daeac2427410cf271"
    )
    assert (
        digest_json(execution.SemanticExecutionAuthorization.model_json_schema())
        == "bd723bf96a62e338706b827adc010d8315f2e6e5260d4b22da526330dcb2b97d"
    )


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_only_exact_known_prompt_artifacts_resolve(version):
    rubric = "Inspect the frozen behavior.\n"
    prompt = calibration.semantic_prompt_for_version(rubric, version=version)
    assert calibration.resolve_semantic_prompt(rubric, prompt.encode()) == (version, prompt)
    assert calibration.semantic_prompt_for_version(rubric.strip(), version=version) == prompt
    if version == "v1":
        assert prompt == calibration.semantic_prompt(rubric)
    else:
        assert prompt.startswith(calibration.semantic_prompt(rubric))
        assert "every finding, including FAIL and UNRESOLVED" in prompt
        assert "node_id" in prompt and "decoded file string" in prompt
        assert "trailing newline does not add an extra line" in prompt
        assert "concise" in prompt


@pytest.mark.parametrize(
    "mutation", ["newline", "prefix", "crlf", "rubric", "unicode", "modified", "text"]
)
@pytest.mark.parametrize("version", ["v1", "v2"])
def test_unknown_or_modified_artifact_never_falls_back(version, mutation):
    prompt = calibration.semantic_prompt_for_version("Owned rubric", version=version).encode()
    mutated = {
        "newline": prompt + b"\n",
        "prefix": b"v2\n" + prompt,
        "crlf": prompt.replace(b"\n", b"\r\n"),
        "rubric": prompt.replace(b"Owned rubric", b"Other rubric"),
        "unicode": b"\xff" + prompt,
        "modified": prompt.replace(b"candidate-file", b"source-file"),
        "text": prompt.decode(),
    }[mutation]
    with pytest.raises(calibration.SemanticCalibrationFailure):
        calibration.resolve_semantic_prompt("Owned rubric", mutated)


@pytest.mark.parametrize("version", ["latest", "V2", "v3", None, 2])
def test_preparation_version_requires_explicit_supported_choice(version):
    with pytest.raises(calibration.SemanticCalibrationFailure):
        calibration.semantic_prompt_for_version("Owned rubric", version=version)


@pytest.mark.parametrize("version", ["v1", "v2"])
async def test_completed_calibration_receipts_wire_bytes_and_cached_readback(
    build, monkeypatch, version
):
    case = await build()
    old_spec = case.spec.model_dump(mode="json")
    fixture_bytes = [case.artifacts.get(row.context_artifact) for row in case.spec.fixtures]
    expectation_bytes = [
        case.expectations.get(row.expectation_artifact) for row in case.spec.fixtures
    ]
    rubric = case.artifacts.get(case.spec.rubric_artifact).decode()
    prompt = calibration.semantic_prompt_for_version(rubric, version=version)
    if version == "v2":
        pin_calibration_prompt(case, prompt.encode())
        assert {
            key for key in old_spec if old_spec[key] != case.spec.model_dump(mode="json")[key]
        } == {"prompt_artifact"}
    wires = []

    async def capture(request):
        wires.append(json.loads(request.content))

    case.model.client.event_hooks["request"].append(capture)
    ref = await run(case)
    evidence = validate(case, ref)
    assert evidence.status == "CALIBRATED" and evidence.metrics.matched_cases == 5
    plan = calibration.SemanticCalibrationPlan.model_validate(
        calibration._read(case.artifacts, evidence.plan_artifact)
    )
    rows = []
    for invocation, wire in zip(plan.cases, wires, strict=True):
        assert wire["system"] == prompt
        context = calibration._read(case.artifacts, invocation.context_artifact)
        row = case.ledger.operation_receipt(plan.account_id, invocation.operation_id)
        rows.append(row)
        receipt = validate_operation_receipt(
            row, account_id=plan.account_id, operation_id=invocation.operation_id
        )
        forecast = forecast_request(
            case.config,
            instructions=prompt,
            context=context,
            output_type=calibration.SemanticScoringOutput,
        )
        assert receipt.prompt_digest == hashlib.sha256(prompt.encode()).hexdigest()
        assert receipt.request_digest == forecast.request_digest
        assert row["reserved_microdollars"] == forecast.reservation_microdollars
    # Merely preparing v2 can never migrate a completed v1 record.
    case.artifacts.put(calibration.semantic_prompt_for_version(rubric, version="v2").encode())
    before = case.ledger.account(plan.account_id)
    monkeypatch.delenv(case.config.api_key_env)
    assert await run(case) == ref and validate(case, ref) == evidence
    assert len(wires) == len(case.requests) == 5
    assert case.ledger.account(plan.account_id) == before
    assert rows == [
        case.ledger.operation_receipt(plan.account_id, row.operation_id) for row in plan.cases
    ]
    assert fixture_bytes == [case.artifacts.get(row.context_artifact) for row in case.spec.fixtures]
    assert expectation_bytes == [
        case.expectations.get(row.expectation_artifact) for row in case.spec.fixtures
    ]


async def test_completed_v1_account_cannot_rebind_to_v2(build):
    case = await build()
    ref = await run(case)
    before = case.ledger.account(case.state["grant"].account_id)
    rubric = case.artifacts.get(case.spec.rubric_artifact).decode()
    pin_calibration_prompt(
        case, calibration.semantic_prompt_for_version(rubric, version="v2").encode()
    )
    with pytest.raises(calibration.SemanticCalibrationFailure):
        validate(case, ref)
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 5 and case.ledger.account(before["id"]) == before


async def test_unknown_prompt_pinned_in_new_spec_denies_before_account_or_call(build):
    case = await build()
    pin_calibration_prompt(case, b"An unrecognized arbitrary prompt")
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert case.requests == []
    with pytest.raises(ValueError):
        case.ledger.account(case.state["grant"].account_id)


async def test_v2_does_not_relax_out_of_range_citation_validation(build):
    case = await build()
    rubric = case.artifacts.get(case.spec.rubric_artifact).decode()
    pin_calibration_prompt(
        case, calibration.semantic_prompt_for_version(rubric, version="v2").encode()
    )
    case.state["fault"] = "bad_citation"
    ref = await run(case)
    result = validate(case, ref, require_pass=False)
    assert result.status == "CALIBRATION_FAILED" and result.metrics.valid_outputs == 4
    assert result.metrics.model_microdollars == 900
    with pytest.raises(calibration.SemanticCalibrationFailure):
        validate(case, ref)


async def test_v2_still_requires_acceptance_nodes_on_each_finding(build):
    case = await build()
    rubric = case.artifacts.get(case.spec.rubric_artifact).decode()
    pin_calibration_prompt(
        case, calibration.semantic_prompt_for_version(rubric, version="v2").encode()
    )
    original_transport = case.model.client._transport

    async def omit_nodes(request):
        response = await original_transport.handle_async_request(request)
        document = response.json()
        output = json.loads(document["content"][0]["text"])
        for finding in output["findings"]:
            for citation in finding["citations"]:
                citation["node_id"] = None
        document["content"][0]["text"] = json.dumps(output)
        return httpx.Response(200, json=document)

    async with httpx.AsyncClient(transport=httpx.MockTransport(omit_nodes)) as client:
        case.model.client = client
        reference = await run(case)
        evidence = validate(case, reference, require_pass=False)
    assert evidence.status == "CALIBRATION_FAILED"
    assert evidence.metrics.valid_outputs == evidence.metrics.matched_cases == 0
    assert evidence.metrics.matched_verdicts == 5
    assert evidence.metrics.model_microdollars == 900 and len(case.requests) == 5


async def test_semantic_executor_uses_exact_v2_with_same_schema_and_account(executed):
    case = executed
    grant = case.state["grant"]
    spec = calibration.SemanticCalibrationSpec.model_validate(
        calibration._read(case.case.protected, grant.calibration_spec_artifact)
    )
    rubric = case.case.protected.get(grant.rubric_artifact).decode()
    prompt = calibration.semantic_prompt_for_version(rubric, version="v2")
    prompt_ref = case.case.protected.put(prompt.encode())
    spec_ref = calibration._put(
        case.case.protected, spec.model_copy(update={"prompt_artifact": prompt_ref})
    )
    # This fixture substitutes calibration authentication, not the prompt/reservation/receipt path.
    object.__setattr__(case.execution.calibration, "spec_artifact", spec_ref)
    case.state["grant"] = grant.model_copy(
        update={"prompt_artifact": prompt_ref, "calibration_spec_artifact": spec_ref}
    )
    case.state["policy"] = case.state["policy"].model_copy(
        update={
            "approved_authorization_digests": (
                digest_json(case.state["grant"].model_dump(mode="json")),
            )
        }
    )
    wires = []

    async def capture(request):
        wires.append(json.loads(request.content))

    case.model.client.event_hooks["request"].append(capture)
    ref = await execution.run_semantic_scoring(execution=case.execution, model=case.model)
    result = execution.validate_semantic_scoring(ref, execution=case.execution)
    assert result.strict_success and len(case.requests) == 2
    assert all(wire["instructions"] == prompt for wire in wires)
    before = case.case.ledger.account(grant.account_id)
    # Replacing an already pinned valid artifact with unknown bytes is never tolerated.
    bad = case.case.protected.put(prompt.encode() + b"\n")
    bad_spec = calibration._put(
        case.case.protected, spec.model_copy(update={"prompt_artifact": bad})
    )
    object.__setattr__(case.execution.calibration, "spec_artifact", bad_spec)
    case.state["grant"] = case.state["grant"].model_copy(
        update={"prompt_artifact": bad, "calibration_spec_artifact": bad_spec}
    )
    case.state["policy"] = case.state["policy"].model_copy(
        update={
            "approved_authorization_digests": (
                digest_json(case.state["grant"].model_dump(mode="json")),
            )
        }
    )
    with pytest.raises(execution.SemanticExecutionFailure):
        await execution.run_semantic_scoring(execution=case.execution, model=case.model)
    assert len(case.requests) == 2 and case.case.ledger.account(grant.account_id) == before
