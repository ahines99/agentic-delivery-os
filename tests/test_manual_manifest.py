"""Synthetic pending-manual reference chains and controlled draft publication."""

import json
from copy import deepcopy

import httpx
import pytest
from test_evidence_manifest import manifest_fixture, put
from test_github_adapter import fixture as github_fixture
from test_github_adapter import mock_github_provider

from agentic_delivery.agents.evidence import validate_manifest
from agentic_delivery.integrations.github import GitHubPublisher, evidence_markdown
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def add_manual(artifacts, manifest):
    criterion = {
        "id": "AC-M",
        "description": "Owner inspects presentation",
        "verification_type": "manual_review",
    }
    for artifact_key, digest_key in (
        ("input_spec_artifact", "input_spec_digest"),
        ("assessed_item_artifact", "spec_digest"),
    ):
        item = json.loads(artifacts.get(manifest[artifact_key]))
        item["acceptance_criteria"].append(criterion)
        manifest[artifact_key] = put(artifacts, item)
        manifest[digest_key] = digest_json(item)
    approved = json.loads(artifacts.get(manifest["approved_plan_digest"]))
    approved["plan"]["criteria"].append(criterion)
    manifest["approved_plan_digest"] = put(artifacts, approved)
    manifest["plan_digest"] = digest_json(approved["plan"])
    review = manifest["attempts"][-1]["review"]
    review["criterion_verdicts"].append({"criterion_id": "AC-M", "result": "UNKNOWN"})
    manifest["review_artifact"] = put(artifacts, review)
    manifest["schema_version"] = 2
    manifest["pending_manual_criteria"] = ["AC-M"]
    return manifest


def test_v2_pending_requires_explicit_profile_and_does_not_change_v1(tmp_path):
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    v1, _ = validate_manifest(settings, repository, "run-1", put(artifacts, manifest))
    assert v1 == manifest
    pending = add_manual(artifacts, manifest)
    digest = put(artifacts, pending)
    with pytest.raises(ValueError):
        validate_manifest(settings, repository, "run-1", digest)
    accepted, _ = validate_manifest(
        settings, repository, "run-1", digest, allow_pending_manual=True
    )
    assert accepted == pending
    assert accepted["pending_manual_criteria"] == ["AC-M"]


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_pending",
        "empty_pending",
        "duplicate_pending",
        "unknown_pending",
        "automated_pending",
        "model_pass",
        "model_fail",
        "missing_verdict",
        "manual_test",
        "missing_automated_test",
        "failed_automated_test",
        "legacy_version",
        "stale_configuration",
    ],
)
def test_pending_manual_manifest_cannot_bypass_evidence(tmp_path, tamper):
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    manifest = add_manual(artifacts, manifest)
    final = manifest["attempts"][-1]
    if tamper == "missing_pending":
        manifest.pop("pending_manual_criteria")
    elif tamper == "empty_pending":
        manifest["pending_manual_criteria"] = []
    elif tamper == "duplicate_pending":
        manifest["pending_manual_criteria"] *= 2
    elif tamper == "unknown_pending":
        manifest["pending_manual_criteria"] = ["AC-other"]
    elif tamper == "automated_pending":
        manifest["pending_manual_criteria"] = ["AC-1", "AC-M"]
    elif tamper in {"model_pass", "model_fail", "missing_verdict"}:
        if tamper == "missing_verdict":
            final["review"]["criterion_verdicts"].pop()
        else:
            final["review"]["criterion_verdicts"][-1]["result"] = (
                "PASS" if tamper == "model_pass" else "FAIL"
            )
        manifest["review_artifact"] = put(artifacts, final["review"])
    elif tamper == "manual_test":
        final["criteria"]["AC-M"] = deepcopy(final["criteria"]["AC-1"])
    elif tamper == "missing_automated_test":
        final["criteria"].pop("AC-1")
    elif tamper == "failed_automated_test":
        final["criteria"]["AC-1"]["passed"] = False
    elif tamper == "legacy_version":
        manifest["schema_version"] = 1
        manifest.pop("pending_manual_criteria")
    elif tamper == "stale_configuration":
        manifest["configuration_digest"] = "0" * 64
    with pytest.raises(ValueError):
        validate_manifest(
            settings, repository, "run-1", put(artifacts, manifest), allow_pending_manual=True
        )


async def test_pending_publication_stays_draft_and_is_explicitly_opted_in(tmp_path, monkeypatch):
    settings, repository, digest = github_fixture(tmp_path, monkeypatch)
    artifacts = ArtifactStore(tmp_path)
    manifest = add_manual(artifacts, json.loads(artifacts.get(digest)))
    digest = put(artifacts, manifest)
    provider, state, counts = mock_github_provider()
    requests = []

    def transport(request):
        requests.append((request.method, request.url.path))
        return provider(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        publisher = GitHubPublisher(settings, repository, client)
        with pytest.raises(ValueError):
            await publisher.publish("run-1", digest)
        assert requests == []
        first = await publisher.publish("run-1", digest, allow_pending_manual=True)
        second = await publisher.publish("run-1", digest, allow_pending_manual=True)
    assert first == second
    assert counts["pull_posts"] == 1
    assert state["pull"]["draft"] is True
    assert "AC-M | PENDING" in state["pull"]["body"]
    assert "AC-1 | PASS" in state["pull"]["body"]
    assert "block review readiness and the Linear handoff" in state["pull"]["body"]
    assert not any(path.endswith("/merge") for _, path in requests)


def test_pending_markdown_cannot_inject_table_or_html(tmp_path):
    _, _, manifest = manifest_fixture(tmp_path)
    manifest["pending_manual_criteria"] = ["AC-M|\n<script>"]
    rendered = evidence_markdown(manifest, "a" * 64)
    assert "AC-M\\| &lt;script> | PENDING" in rendered
    assert "## Verified candidate" not in rendered
