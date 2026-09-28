"""Owned candidate machinery: actual broker/ledger, controlled qualification and Docker."""
# ruff: noqa: F401, F811

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, update
from test_campaign_allocation import (
    allocation_case,
    campaign_scoring,
    campaign_seed,
    controlled_scoring,
)

from agentic_delivery.agents.pipeline import BUILD_INSTRUCTIONS, REVIEW_INSTRUCTIONS
from agentic_delivery.config import CommandProfile, ModelConfig
from agentic_delivery.evaluation import campaign_candidate as candidate
from agentic_delivery.evaluation import execution_store
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_runtime import PREFLIGHT_CHECKS
from agentic_delivery.execution.docker import ExecutionResult
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.store import digest_json


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


@pytest.fixture
def candidate_case(allocation_case, monkeypatch, request):
    c = allocation_case
    case = c.case
    selected = getattr(request, "param", "A")
    arm_name, mode = selected if isinstance(selected, tuple) else (selected, "controlled")
    image = os.environ.get("TEST_SANDBOX_IMAGE") if mode == "docker" else None
    if mode == "docker" and not image:
        pytest.skip("Pinned candidate Docker image not configured")
    campaign = json.loads(case.frozen_store.get(c.state["grant"].campaign_artifact))
    ordinal = next(
        row["ordinal"]
        for row in campaign["schedule"]
        if row["task_id"] == case.task.id and row["arm"] == arm_name and row["kind"] == "primary"
    )
    source = {
        "app.py": "VALUE = 1\n",
        "tests/test_regression.py": (
            "from app import VALUE\ndef test_existing():\n"
            "    assert isinstance(VALUE, int) and VALUE >= 1\n"
        ),
    }
    if mode == "large":
        source["large.py"] = "# " + "x" * 120000 + "\n"
    command = CommandProfile(
        id="regression",
        argv=("python", "-m", "pytest", "-q", "tests/test_regression.py::test_existing"),
        expected_tests=1,
    )
    case.task = case.task.model_copy(
        update={
            "snapshot_artifact": put(case.protected, source),
            "regression_commands": (command,),
            "image": image or case.task.image,
        }
    )
    settings = case.state["settings"]
    case.state["settings"] = settings.model_copy(
        update={
            "repositories": (
                settings.repositories[0].model_copy(
                    update={"commands": (command,), "sandbox_image": image or case.task.image}
                ),
            )
        }
    )
    for entry in campaign["tasks"]:
        if entry["task_id"] == case.task.id:
            entry["task_manifest_digest"] = qualification_task_digest(
                case.task.model_dump(mode="json")
            )
    campaign["manifest_digest"] = digest_json(campaign["tasks"])
    refs = {}
    for ref in campaign["specification"]["arms"]:
        arm = json.loads(case.protected.get(ref["configuration_artifact"]))
        arm["policy_digest"] = put(
            case.protected, candidate.supported_policy_profile().model_dump(mode="json")
        )
        arm["tool_permissions_digest"] = put(
            case.protected, candidate.CandidateToolProfile().model_dump(mode="json")
        )
        arm["builder_prompt_digest"] = case.protected.put(BUILD_INSTRUCTIONS.encode())
        arm["review_prompt_digest"] = (
            case.protected.put(REVIEW_INSTRUCTIONS.encode()) if arm["arm"] == "B" else None
        )
        ref["configuration_artifact"] = put(case.protected, arm)
        refs[arm["arm"]] = (ref["configuration_artifact"], arm)
    frozen_ref = put(case.frozen_store, campaign)
    selected_ref, arm = refs[arm_name]
    c.state["policy"] = c.state["policy"].model_copy(
        update={"campaign_artifact": frozen_ref, "approved_ordinals": (ordinal,)}
    )
    c.state["grant"] = c.state["grant"].model_copy(
        update={
            "campaign_artifact": frozen_ref,
            "ordinal": ordinal,
            "arm_configuration_artifact": selected_ref,
            "task_manifest_digest": qualification_task_digest(case.task.model_dump(mode="json")),
            "execution_config_digest": case.state["settings"].execution_digest(
                case.task.item.repository
            ),
            "allocation_policy_digest": digest_json(c.state["policy"].model_dump(mode="json")),
        }
    )
    c.account_id = canonical_account_id(frozen_ref, ordinal)
    original_admission = HistoricalTask.validate_qualification

    def admitted(task, artifacts, *, authority, purpose):
        return original_admission(
            task,
            artifacts,
            authority=authority,
            purpose="campaign" if purpose == "worker-export" else purpose,
        )

    monkeypatch.setattr(HistoricalTask, "validate_qualification", admitted)
    allocated = c.create().allocate(case.task)
    config = ModelConfig.model_validate(arm["model"])
    policy = candidate.CandidateExecutionPolicy(
        enabled=True,
        approved_attempt_bindings=(allocated.attempt_binding_artifact,),
        approved_model_configurations=(digest_json(config.model_dump(mode="json")),),
        microdollars_per_second=1,
        rate_card_version="owned-candidate",
    )
    auth = candidate.CandidateAuthorization(
        account_id=c.account_id,
        campaign_artifact=frozen_ref,
        ordinal=ordinal,
        phase="development",
        arm_configuration_artifact=selected_ref,
        attempt_binding_artifact=allocated.attempt_binding_artifact,
        task_manifest_digest=allocated.attempt.task_manifest_digest,
        qualification_artifact=case.task.qualification_artifact,
        candidate_policy_digest=digest_json(policy.model_dump(mode="json")),
        model_configuration_digest=digest_json(config.model_dump(mode="json")),
        execution_config_digest=c.state["grant"].execution_config_digest,
        preparation_policy_digest=c.state["grant"].preparation_policy_digest,
        issued_at=datetime.now(UTC),
        expires_at=allocated.attempt.deadline,
    )
    state = {
        "policy": policy,
        "grant": auth,
        "reject": False,
        "always_reject": False,
        "http_failure": False,
        "protected_edit": False,
        "validation_failure": False,
        "calls": [],
        "docker": [],
    }
    monkeypatch.setenv(config.api_key_env, "owned-not-a-real-provider-key")

    async def transport(request):
        body = json.loads(request.content)
        context = json.loads(body["input"])
        build = body["text"]["format"]["name"] == "BuildProposal"
        state["calls"].append(("build" if build else "review", context))
        if state.get("block"):
            state["entered"].set()
            await asyncio.Event().wait()
        if state.get("revoke_after_provider"):
            state["policy"] = state["policy"].model_copy(update={"enabled": False})
        if state["http_failure"]:
            return httpx.Response(503, json={"error": "owned provider refusal"})
        if build:
            files = context["files"]
            count = sum(role == "build" for role, _ in state["calls"])
            text = "VALUE = " + str(count + 1) + "\n"
            tests = "from app import VALUE\ndef test_added():\n    assert VALUE > 1\n"
            target = {**files, "app.py": text, "tests/test_added.py": tests}
            if state["protected_edit"]:
                target["tests/test_regression.py"] = "def test_existing(): pass\n"
            answer = {
                "summary": "Owned controlled implementation",
                "edits": [
                    {
                        "path": path,
                        "original_sha256": hashlib.sha256(files[path].encode()).hexdigest()
                        if path in files
                        else None,
                        "content": content,
                    }
                    for path, content in target.items()
                    if files.get(path) != content
                ],
                "criterion_tests": [
                    {
                        "criterion_id": case.task.item.acceptance_criteria[0].id,
                        "tests": ["tests/test_added.py::test_added"],
                    }
                ],
            }
        else:
            count = sum(role == "review" for role, _ in state["calls"])
            approved = not state["always_reject"] and (not state["reject"] or count > 1)
            answer = {
                "decision": "APPROVE" if approved else "REQUEST_CHANGES",
                "summary": "Owned controlled review",
                "findings": [],
                "criterion_verdicts": [
                    {
                        "criterion_id": case.task.item.acceptance_criteria[0].id,
                        "result": "PASS" if approved else "FAIL",
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "owned-response-"
                + ("same" if state.get("duplicate_response") else str(len(state["calls"]))),
                "model": config.model,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(answer)}],
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    class Runner:
        def __init__(self, image):
            self.image = image

        async def preflight(self, *, run_id=None):
            state["docker"].append(("preflight", run_id))
            return {"image": self.image, "checks": {name: True for name in PREFLIGHT_CHECKS}}

        async def run(self, files, argv, *, timeout_seconds, run_id, verification_binding):
            state["docker"].append(("verify", run_id, files, argv, timeout_seconds))
            nodes = pytest_selectors(argv)
            failed = state["validation_failure"] and "tests/test_added.py" in files
            report = {
                "collector_version": 1,
                "binding": verification_binding,
                "session_started": True,
                "session_finished": True,
                "main_returned": True,
                "exit_code": 1 if failed else 0,
                "collected": list(nodes),
                "collection_errors": [],
                "deselected": [],
                "phases": [
                    {
                        "nodeid": node,
                        "when": when,
                        "outcome": "failed" if failed and when == "call" else "passed",
                        "wasxfail": False,
                    }
                    for node in nodes
                    for when in ("setup", "call", "teardown")
                ],
            }
            if state.get("missing_nonce"):
                verification_binding.pop("nonce")
            return ExecutionResult(
                1 if failed else 0,
                "owned stdout",
                "",
                0.001,
                self.image,
                verification_report=report,
            )

    if mode != "docker":
        monkeypatch.setattr(candidate, "DockerRunner", Runner)
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    model = StructuredModel(config, case.ledger, client)

    def create():
        return candidate.CampaignCandidateExecution(
            allocator=c.create(),
            model=model,
            authorization_provider=lambda: state["grant"],
            policy_provider=lambda: state["policy"],
        )

    return SimpleNamespace(
        allocation=c,
        case=case,
        state=state,
        model=model,
        create=create,
        config=config,
        client=client,
        arm=arm,
        allocated=allocated,
    )


@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_candidate_adapter_preserves_budget_and_seals_one_way_output(candidate_case):
    c = candidate_case
    task_before = c.case.task.model_dump_json()
    result = await c.create().run(c.case.task)
    assert result.status == ("BUILD_VERIFIED" if c.arm["arm"] == "A" else "REVIEW_APPROVED")
    assert result.strict_success is False and result.candidate_artifact
    assert sum(role == "review" for role, _ in c.state["calls"]) == (c.arm["arm"] == "B")
    assert c.case.task.model_dump_json() == task_before
    assert all(call[-1] == 7 for call in c.state["docker"] if call[0] == "verify")
    base = json.loads(c.case.protected.get(c.case.task.snapshot_artifact))
    files = json.loads(c.case.output.get(result.candidate_artifact))
    assert files["tests/test_regression.py"] == base["tests/test_regression.py"]
    for _, context in c.state["calls"]:
        document = json.dumps(context)
        assert (
            c.case.task.oracle_artifact not in document
            and c.case.task.reference_patch_artifact not in document
        )
        assert "qualification_artifact" not in document and "model_microdollars" not in document
    account = c.case.ledger.account(c.allocation.account_id)
    assert account["reserved_microdollars"] == 0 and account["model_spent_microdollars"] > 0
    assert account["infrastructure_spent_microdollars"] > 0
    before = (len(c.state["calls"]), len(c.state["docker"]), account)
    assert await c.create().run(c.case.task) == result
    assert before == (
        len(c.state["calls"]),
        len(c.state["docker"]),
        c.case.ledger.account(c.allocation.account_id),
    )
    await c.client.aclose()


@pytest.mark.parametrize("candidate_case", ["B"], indirect=True)
async def test_review_repair_has_fresh_checks_and_preserves_both_candidates(candidate_case):
    c = candidate_case
    c.state["reject"] = True
    result = await c.create().run(c.case.task)
    assert result.status == "REVIEW_APPROVED"
    assert [role for role, _ in c.state["calls"]] == ["build", "review", "build", "review"]
    evidence = json.loads(c.case.output.get(result.engine_evidence_artifact))
    assert len(evidence["attempts"]) == 2
    assert c.state["calls"][1][1]["candidate_files"] != c.state["calls"][3][1]["candidate_files"]
    assert len(c.state["docker"]) == 6
    await c.client.aclose()


@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_normal_exhaustion_retains_candidate_without_success(candidate_case):
    c = candidate_case
    c.state["always_reject"] = True
    c.state["validation_failure"] = c.arm["arm"] == "A"
    result = await c.create().run(c.case.task)
    assert result.status == "FAILED" and result.candidate_artifact and not result.strict_success
    assert (
        sum(role == "build" for role, _ in c.state["calls"]) == c.arm["limits"]["repair_rounds"] + 1
    )
    assert c.case.ledger.account(c.allocation.account_id)["reserved_microdollars"] == 0
    await c.client.aclose()


async def test_unknown_provider_outcome_is_not_reissued(candidate_case):
    c = candidate_case
    c.state["http_failure"] = True
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    before = (len(c.state["calls"]), len(c.state["docker"]))
    assert c.case.ledger.account(c.allocation.account_id)["reserved_microdollars"] > 0
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert before == (len(c.state["calls"]), len(c.state["docker"]))
    await c.client.aclose()


async def test_protected_edit_cannot_seal_candidate(candidate_case):
    c = candidate_case
    c.state["protected_edit"] = True
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert (
        c.case.ledger.checkpoint_receipt(c.allocation.account_id, candidate.RESULT_CHECKPOINT)
        is None
    )
    assert c.case.ledger.account(c.allocation.account_id)["model_spent_microdollars"] > 0
    await c.client.aclose()


@pytest.mark.parametrize(
    "fault",
    [
        "account",
        "campaign",
        "ordinal",
        "phase",
        "arm",
        "attempt",
        "task",
        "qualification",
        "model",
        "policy",
        "configuration",
        "preparation",
        "expired",
        "future",
    ],
)
async def test_grant_tampering_denies_before_worker_export(candidate_case, monkeypatch, fault):
    c = candidate_case
    mapping = {
        "account": "account_id",
        "campaign": "campaign_artifact",
        "arm": "arm_configuration_artifact",
        "attempt": "attempt_binding_artifact",
        "task": "task_manifest_digest",
        "qualification": "qualification_artifact",
        "model": "model_configuration_digest",
        "policy": "candidate_policy_digest",
        "configuration": "execution_config_digest",
        "preparation": "preparation_policy_digest",
    }
    updates = (
        {mapping[fault]: "f" * 64}
        if fault in mapping
        else {
            "ordinal": {"ordinal": 999},
            "phase": {"phase": "test"},
            "expired": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
            "future": {"issued_at": datetime.now(UTC) + timedelta(seconds=10)},
        }[fault]
    )
    c.state["grant"] = c.state["grant"].model_copy(update=updates)
    original = c.case.protected.get

    def deny_export(ref):
        if ref == c.case.task.snapshot_artifact:
            pytest.fail("Unapproved candidate grant read worker source")
        return original(ref)

    monkeypatch.setattr(c.case.protected, "get", deny_export)
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == c.state["docker"] == []
    await c.client.aclose()


@pytest.mark.parametrize("candidate_case", [("A", "large")], indirect=True)
async def test_large_context_refuses_frozen_cap_without_truncation_or_network(candidate_case):
    c = candidate_case
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == [] and len(c.state["docker"]) == 2
    account = c.case.ledger.account(c.allocation.account_id)
    assert account["model_spent_microdollars"] == account["reserved_microdollars"] == 0
    await c.client.aclose()


@pytest.mark.parametrize("resource", ["model", "infrastructure"])
async def test_prior_shared_usage_cannot_gain_candidate_capacity(candidate_case, resource):
    c = candidate_case
    ledger, account = c.case.ledger, c.allocation.account_id
    if resource == "model":
        cost = c.arm["limits"]["model_microdollars"]
        ledger.reserve(account, "owned-prior-build", cost, 1, 1)
        ledger.settle("owned-prior-build", cost=cost, input_tokens=1, output_tokens=1, result={})
    else:
        cost = c.arm["limits"]["infrastructure_microdollars"]
        ledger.reserve_infrastructure(
            account,
            "owned-prior-runner",
            max_seconds=cost,
            microdollars_per_second=1,
            rate_card_version="owned",
            binding_digest="f" * 64,
        )
        ledger.settle_infrastructure(
            "owned-prior-runner", elapsed_milliseconds=cost * 1000, result={}
        )
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == [] and ledger.account(account)["spent_microdollars"] >= cost
    if resource == "infrastructure":
        assert c.state["docker"] == []
    await c.client.aclose()


async def test_revocation_after_response_retains_usage_and_no_further_effect(candidate_case):
    c = candidate_case
    c.state["revoke_after_provider"] = True
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert len(c.state["calls"]) == 1 and len(c.state["docker"]) == 2
    assert c.case.ledger.account(c.allocation.account_id)["model_spent_microdollars"] > 0
    assert (
        c.case.ledger.checkpoint_receipt(c.allocation.account_id, candidate.RESULT_CHECKPOINT)
        is None
    )
    await c.client.aclose()


@pytest.mark.parametrize("fault", ["policy", "deadline", "qualification"])
async def test_active_guard_cancels_owned_provider_and_retains_uncertainty(candidate_case, fault):
    c = candidate_case
    c.state.update(block=True, entered=asyncio.Event())
    work = asyncio.create_task(c.create().run(c.case.task))
    await asyncio.wait_for(c.state["entered"].wait(), timeout=5)
    if fault == "policy":
        c.state["policy"] = c.state["policy"].model_copy(update={"enabled": False})
    elif fault == "deadline":
        c.case.state["now"] = c.allocated.attempt.deadline + timedelta(seconds=1)
    else:
        c.case.state["revoked"] = True
    with pytest.raises(candidate.CandidateFailure):
        await asyncio.wait_for(work, timeout=5)
    assert c.case.ledger.account(c.allocation.account_id)["reserved_microdollars"] > 0
    assert len(c.state["calls"]) == 1 and len(c.state["docker"]) == 2
    receipt = c.case.ledger.operation_receipt(
        c.allocation.account_id, c.allocation.account_id + ":candidate:build:0"
    )
    assert receipt["status"] == "RESERVED" and receipt["observation"]["outcome"] == "CANCELLED"
    await c.client.aclose()


@pytest.mark.integration
@pytest.mark.parametrize("candidate_case", [("A", "docker"), ("B", "docker")], indirect=True)
async def test_owned_candidate_actual_docker_with_controlled_model(candidate_case):
    c = candidate_case
    c.state["reject"] = c.arm["arm"] == "B"
    result = await c.create().run(c.case.task)
    assert result.status == ("BUILD_VERIFIED" if c.arm["arm"] == "A" else "REVIEW_APPROVED")
    assert result.candidate_artifact
    operations = json.loads(c.case.output.get(result.operations_artifact))
    expected_calls = 1 if c.arm["arm"] == "A" else 4
    assert len(operations) == (5 if c.arm["arm"] == "A" else 10)
    assert len(c.state["calls"]) == expected_calls
    assert c.case.ledger.account(c.allocation.account_id)["reserved_microdollars"] == 0
    before = c.case.ledger.account(c.allocation.account_id)
    assert await c.create().run(c.case.task) == result
    assert (
        c.case.ledger.account(c.allocation.account_id) == before
        and len(c.state["calls"]) == expected_calls
    )
    await c.client.aclose()


@pytest.mark.parametrize("stage", ["build:0", "preflight", "verify:0"])
async def test_missing_sealed_operation_never_reissues_effect(candidate_case, stage):
    c = candidate_case
    await c.create().run(c.case.task)
    before = (len(c.state["calls"]), len(c.state["docker"]))
    operation_id = c.allocation.account_id + ":candidate:" + stage
    with c.case.ledger.engine.begin() as connection:
        connection.execute(
            delete(execution_store.operations).where(
                execution_store.operations.c.id == operation_id
            )
        )
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert before == (len(c.state["calls"]), len(c.state["docker"]))
    await c.client.aclose()


async def test_partial_input_marker_without_operation_is_not_silently_reissued(
    candidate_case, monkeypatch
):
    c = candidate_case
    original = c.case.ledger.reserve_infrastructure

    def stop(*args, **kwargs):
        raise RuntimeError("owned crash before effect reservation")

    monkeypatch.setattr(c.case.ledger, "reserve_infrastructure", stop)
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    monkeypatch.setattr(c.case.ledger, "reserve_infrastructure", original)
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == c.state["docker"] == []
    await c.client.aclose()


async def test_invalid_collector_binding_cannot_feed_worker_or_seal(candidate_case):
    c = candidate_case
    c.state["missing_nonce"] = True
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == []
    assert (
        c.case.ledger.checkpoint_receipt(c.allocation.account_id, candidate.RESULT_CHECKPOINT)
        is None
    )
    assert c.case.ledger.account(c.allocation.account_id)["infrastructure_spent_microdollars"] > 0
    await c.client.aclose()


@pytest.mark.parametrize("candidate_case", ["B"], indirect=True)
async def test_provider_response_id_reuse_cannot_seal_independent_review(candidate_case):
    c = candidate_case
    c.state["duplicate_response"] = True
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert [kind for kind, _ in c.state["calls"]] == ["build", "review"]
    assert c.case.ledger.account(c.allocation.account_id)["reserved_microdollars"] == 0
    assert (
        c.case.ledger.checkpoint_receipt(c.allocation.account_id, candidate.RESULT_CHECKPOINT)
        is None
    )
    await c.client.aclose()


async def test_worker_projection_has_no_direct_oracle_or_reference_reads(
    candidate_case, monkeypatch
):
    c = candidate_case
    original = c.case.protected.get
    forbidden = {
        c.case.task.oracle_artifact,
        c.case.task.reference_patch_artifact,
        c.case.task.reference_snapshot_artifact,
    }

    def guarded(ref):
        if ref in forbidden:
            pytest.fail("Candidate attempted protected evaluator material read")
        return original(ref)

    monkeypatch.setattr(c.case.protected, "get", guarded)
    result = await c.create().run(c.case.task)
    assert result.status == "BUILD_VERIFIED"
    await c.client.aclose()


async def test_unbound_candidate_operation_prevents_first_effect(candidate_case):
    c = candidate_case
    identity = c.allocation.account_id + ":candidate:unbound"
    c.case.ledger.reserve(c.allocation.account_id, identity, 1, 1, 1)
    c.case.ledger.settle(identity, cost=0, input_tokens=0, output_tokens=0, result={})
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert c.state["calls"] == c.state["docker"] == []
    await c.client.aclose()


@pytest.mark.parametrize(
    "field",
    ["input_microdollars_per_million", "output_microdollars_per_million", "rate_card_version"],
)
async def test_cached_model_receipt_rates_must_match_frozen_configuration(candidate_case, field):
    c = candidate_case
    await c.create().run(c.case.task)
    operation_id = c.allocation.account_id + ":candidate:build:0"
    row = c.case.ledger.operation_receipt(c.allocation.account_id, operation_id)
    stored = json.loads(json.dumps(row["result"]))
    if field == "rate_card_version":
        stored["rate_card_version"] = stored["operation_receipt"][field] = "altered-rate-card"
    else:
        stored["operation_receipt"][field] = 2
    # Fixture usage still rounds to exactly 1 microdollar; request/config hashes and
    # account counters remain unchanged. Exercise recovered stage validation itself.
    with c.case.ledger.engine.begin() as connection:
        connection.execute(
            update(execution_store.operations)
            .where(execution_store.operations.c.id == operation_id)
            .values(result=stored)
        )
        connection.execute(
            delete(execution_store.checkpoints).where(
                execution_store.checkpoints.c.account_id == c.allocation.account_id,
                execution_store.checkpoints.c.stage == candidate.RESULT_CHECKPOINT,
            )
        )
    before = (len(c.state["calls"]), len(c.state["docker"]))
    with pytest.raises(candidate.CandidateFailure):
        await c.create().run(c.case.task)
    assert before == (len(c.state["calls"]), len(c.state["docker"]))
    assert (
        c.case.ledger.checkpoint_receipt(c.allocation.account_id, candidate.RESULT_CHECKPOINT)
        is None
    )
    await c.client.aclose()
