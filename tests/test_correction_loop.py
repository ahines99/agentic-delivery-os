"""Owned correction loops: actual Docker, persisted usage, controlled model HTTP only."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentic_delivery.agents import pipeline
from agentic_delivery.agents.contracts import (
    BuildProposal,
    CriterionTests,
    FileEdit,
    ImplementationPlan,
    ReviewResult,
)
from agentic_delivery.agents.evidence import validate_manifest
from agentic_delivery.config import Budget, CommandProfile, ModelConfig, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import Base, UsageRecord
from agentic_delivery.storage.store import Store, digest_json


@pytest.mark.integration
@pytest.mark.parametrize("repaired", [True, False], ids=["repair-approved", "repair-exhausted"])
async def test_correction_loop_keeps_fresh_evidence_and_all_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repaired: bool
) -> None:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    base = {
        "app.py": "def value():\n    return 1\n",
        "tests/test_existing.py": (
            "from app import value\n\ndef test_existing():\n    assert value() >= 1\n"
        ),
    }
    first = {
        **base,
        "app.py": "def value():\n    return 2\n",
        "tests/test_new.py": (
            "from app import value\n\ndef test_new():\n    assert value() == 2\n"
        ),
    }
    second = {
        **first,
        "app.py": (
            'def value():\n    """Return exactly two."""\n    return 2\n'
            if repaired
            else "def value():\n    return 1 + 1\n"
        ),
    }
    command = CommandProfile(
        id="suite",
        argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"),
    )
    repository = RepositoryConfig(
        id="owned/correction-loop",
        github_owner="owned",
        github_name="correction-loop",
        commands=(command,),
        sandbox_image=image,
        model_data_authorized=True,
    )
    settings = Settings(
        repositories=(repository,),
        artifact_root=tmp_path / "artifacts",
        budget=Budget(repair_rounds=1, command_seconds=30, wall_seconds=180),
        model=ModelConfig(
            provider="anthropic",
            model="owned-http-fixture",
            api_key_env="CORRECTION_TEST_KEY",
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=25_000_000,
            rate_card_version="owned-fixture-not-provider-pricing",
            max_output_tokens=1000,
        ),
    )
    monkeypatch.setenv("CORRECTION_TEST_KEY", "owned-test-not-a-provider-credential")
    item = WorkItem(
        id="owned-correction-loop",
        title="Document and return two",
        description="value() must return two and have the docstring Return exactly two.",
        repository=repository.id,
        risk_tier=1,
        acceptance_criteria=(
            {
                "id": "AC-1",
                "description": "value() returns two with its required docstring.",
                "verification_type": "unit_test",
            },
        ),
    )
    plan = ImplementationPlan(
        disposition="READY",
        summary="Document value and return two, preserving original tests.",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Update value, add a behavior test, and review the required documentation.",),
        files=("app.py", "tests/test_new.py"),
        verification=("Run original and new behavior tests and review the docstring.",),
        rollback="Discard the isolated candidate.",
        assumptions=(),
    )
    rejected = ReviewResult(
        decision="REQUEST_CHANGES",
        summary="Behavior passes, but required documentation is absent.",
        findings=(
            {
                "severity": "blocking",
                "path": "app.py",
                "description": "Add the required function docstring.",
                "evidence": "The candidate function has no docstring.",
            },
        ),
        criterion_verdicts=({"criterion_id": "AC-1", "result": "FAIL"},),
    )
    approved = ReviewResult(
        decision="APPROVE",
        summary="The corrected candidate has the required behavior and docstring.",
        findings=(),
        criterion_verdicts=({"criterion_id": "AC-1", "result": "PASS"},),
    )

    def proposal(before: dict[str, str], after: dict[str, str]) -> BuildProposal:
        return BuildProposal(
            summary="Owned scripted candidate, not model capability evidence.",
            edits=tuple(
                FileEdit(
                    path=path,
                    original_sha256=hashlib.sha256(before[path].encode()).hexdigest()
                    if path in before
                    else None,
                    content=content,
                )
                for path, content in after.items()
                if before.get(path) != content
            ),
            criterion_tests=(
                CriterionTests(criterion_id="AC-1", tests=("tests/test_new.py::test_new",)),
            ),
        )

    responses = (
        proposal(base, first),
        rejected,
        proposal(first, second),
        approved if repaired else rejected,
    )
    contexts: list[dict] = []
    container_ids: list[str] = []
    runners: list[DockerRunner] = []

    def transport(request: httpx.Request) -> httpx.Response:
        # The adapter, parser, reservations and settlements are production code;
        # only the HTTP response is controlled. No external request is performed.
        body = json.loads(request.content)
        index = len(contexts)
        assert index < len(responses), "Correction limit must prevent another model call"
        contexts.append(json.loads(body["messages"][0]["content"]))
        return httpx.Response(
            200,
            json={
                "id": f"owned-response-{index}",
                "model": settings.model.model,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": responses[index].model_dump_json()}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    class ObservedDocker(DockerRunner):
        def __init__(self, image: str):
            super().__init__(image)
            runners.append(self)

        async def cli(self, *args, **kwargs):
            result = await super().cli(*args, **kwargs)
            if args[0] == "create" and result[0] == 0:
                container_ids.append(result[1].decode().strip())
            return result

    monkeypatch.setattr(pipeline, "DockerRunner", ObservedDocker)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
    engine = create_database(database_url)
    Base.metadata.create_all(engine)
    store = Store(engine)
    artifacts = ArtifactStore(settings.artifact_root)

    def put(value: object) -> str:
        return artifacts.put(json.dumps(value, sort_keys=True).encode())

    approved_plan = put(
        {"plan": plan.model_dump(mode="json"), "base_sha": "a" * 40, "snapshot_digest": put(base)}
    )
    identity = store.submit(item, actor="owned-fixture", key=item.id, budget=settings.budget)[
        "workflow_id"
    ]
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            monkeypatch.setattr(
                pipeline,
                "StructuredModel",
                lambda config, ledger: StructuredModel(config, ledger, client),
            )
            result = await pipeline.build_and_review(
                identity,
                item,
                plan,
                base,
                "a" * 40,
                settings,
                store,
                repository,
                approved_plan_digest=approved_plan,
            )
        assert len(contexts) == 4
        attempts = result["manifest"]["attempts"] if repaired else result["attempts"]
        assert [attempt["iteration"] for attempt in attempts] == [0, 1]
        assert attempts[0]["review"] == rejected.model_dump(mode="json")
        assert attempts[1]["review"] == (approved if repaired else rejected).model_dump(mode="json")
        assert contexts[0]["files"] == base and contexts[0]["feedback"] == {}
        assert contexts[2]["files"] == first and contexts[2]["feedback"] == attempts[0]
        assert (
            contexts[2]["file_sha256"]["app.py"]
            == hashlib.sha256(first["app.py"].encode()).hexdigest()
        )
        receipt_digests = []
        nonces = []
        for attempt, files, context in zip(
            attempts, (first, second), (contexts[1], contexts[3]), strict=True
        ):
            assert context["base_files"] == base and context["candidate_files"] == files
            assert context["verification"] == attempt["validation"]
            assert context["criterion_evidence"] == attempt["criteria"]
            for summary, nodes in (
                (
                    attempt["validation"],
                    {"tests/test_existing.py::test_existing", "tests/test_new.py::test_new"},
                ),
                (attempt["criteria"]["AC-1"], {"tests/test_new.py::test_new"}),
            ):
                assert summary["passed"] and summary["snapshot_digest"] == digest_json(files)
                receipt_digest = summary["commands"][0]["artifact_digest"]
                receipt_digests.append(receipt_digest)
                receipt = json.loads(artifacts.get(receipt_digest))
                report = receipt["verification_report"]
                assert receipt["workflow_id"] == identity
                assert receipt["snapshot_digest"] == digest_json(files)
                assert receipt["image"] == image and receipt["exit_code"] == 0
                assert receipt["report_error"] is None and not receipt["timed_out"]
                assert report["binding"] == receipt["verification_binding"]
                assert report["binding"]["snapshot_digest"] == digest_json(files)
                nonces.append(report["binding"]["nonce"])
                assert set(report["collected"]) == nodes and not report["collection_errors"]
                assert {
                    phase["nodeid"] for phase in report["phases"] if phase["when"] == "call"
                } == nodes
                assert all(phase["outcome"] == "passed" for phase in report["phases"])
        assert len(set(receipt_digests)) == len(set(nonces)) == 4
        assert (
            first["tests/test_existing.py"]
            == second["tests/test_existing.py"]
            == base["tests/test_existing.py"]
        )
        if repaired:
            assert result["state"] == "LOCAL_REVIEW_READY"
            manifest, candidate = validate_manifest(
                settings, repository, identity, result["manifest_digest"]
            )
            assert candidate == second and manifest["attempts"] == attempts
            assert json.loads(artifacts.get(manifest["review_artifact"])) == approved.model_dump(
                mode="json"
            )
        else:
            assert result["state"] == "FAILED"
            assert result["reason"] == "Correction budget exhausted"
            assert set(result) == {"state", "reason", "attempts"}
            assert not any(
                "candidate_digest" in json.loads(path.read_bytes())
                for path in settings.artifact_root.glob("*/*")
                if path.is_file()
            )
        # Preflight + baseline + two separate suite/criterion runs per candidate.
        assert len(container_ids) == len(set(container_ids)) == 6
        for container in container_ids:
            code, stdout, _ = await runners[0].cli(
                "ps", "-a", "--filter", "id=" + container, "--format", "{{.ID}}"
            )
            assert code == 0 and stdout.strip() == b""
        put(result)  # Retain the complete result, including exhausted attempts.
    finally:
        engine.dispose()
    # A fresh database engine must observe every call, including rejected reviews.
    recovered_engine = create_database(database_url)
    try:
        recovered = Store(recovered_engine)
        run = recovered.workflow(identity)
        assert run["spent_microdollars"] == 12_000 and run["reserved_microdollars"] == 0
        with Session(recovered_engine) as session:
            operations = session.scalars(
                select(UsageRecord).where(UsageRecord.workflow_id == identity)
            ).all()
            assert {operation.id for operation in operations} == {
                f"{identity}:{role}:{iteration}"
                for role in ("build", "review")
                for iteration in (0, 1)
            }
        for index, (role, iteration) in enumerate(
            (("build", 0), ("review", 0), ("build", 1), ("review", 1))
        ):
            receipt = recovered.operation_receipt(identity, f"{identity}:{role}:{iteration}")
            assert receipt["status"] == "SETTLED" and receipt["actual_microdollars"] == 3000
            assert receipt["actual_input_tokens"] == receipt["actual_output_tokens"] == 100
            provenance = receipt["result"]["operation_receipt"]
            assert provenance["context_digest"] == digest_json(contexts[index])
            assert provenance["provider_response_id"] == f"owned-response-{index}"
    finally:
        recovered_engine.dispose()
