"""Update only the generated evidence section after current human acceptance."""

import re
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import httpx
import jwt

from agentic_delivery.agents.evidence import validate_manifest
from agentic_delivery.config import RepositoryConfig, Settings, secret
from agentic_delivery.integrations.github import GitHubFailure, GitHubPublisher, evidence_markdown


async def confirm_manual_acceptance(
    settings: Settings,
    repository: RepositoryConfig,
    identity: str,
    publication: dict[str, Any],
    acceptance_digest: str,
    *,
    authorization_check: Callable[[], None],
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    authorization_check()
    if (
        not settings.publication_enabled
        or not settings.github_app_id
        or not settings.github_installation_id
        or not repository.github_repository_id
        or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", identity)
        or not re.fullmatch(r"[a-f0-9]{40}", str(publication.get("head_sha", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", acceptance_digest)
        or type(publication.get("number")) is not int
        or publication["number"] <= 0
        or publication.get("status") != "DRAFT_HANDOFF"
    ):
        raise GitHubFailure("Manual acceptance publication is not configured or current")
    manifest, _ = validate_manifest(
        settings, repository, identity, publication["manifest_digest"], allow_pending_manual=True
    )
    if manifest["schema_version"] != 2 or publication["base_sha"] != manifest["base_sha"]:
        raise GitHubFailure("Manual acceptance manifest does not match publication")
    marker = f"<!-- delivery-operation:{identity} manifest:{publication['manifest_digest']} -->"
    previous = evidence_markdown(manifest, publication["manifest_digest"])
    confirmed = evidence_markdown(
        manifest, publication["manifest_digest"], manual_acceptance=acceptance_digest
    )
    confirmed += f"\n\nAccepted head: `{publication['head_sha']}`."
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False)
    token = ""
    route = f"https://api.github.com/repos/{repository.github_owner}/{repository.github_name}/pulls/{publication['number']}"

    def checked_body(pull: Any) -> str:
        if not isinstance(pull, dict):
            raise GitHubFailure("Invalid pull request read-back")
        if (
            type(pull.get("number")) is not int
            or pull.get("number") != publication["number"]
            or pull.get("state") != "open"
            or pull.get("draft") is not True
            or pull.get("merged") is not False
            or not isinstance(pull.get("body"), str)
            or pull["body"].count(marker) != 1
        ):
            raise GitHubFailure("Pull request state or evidence marker changed")
        for side, reference in (("head", "agent/" + identity), ("base", repository.base_branch)):
            revision = pull.get(side)
            if (
                not isinstance(revision, dict)
                or revision.get("sha") != publication[side + "_sha"]
                or revision.get("ref") != reference
                or not isinstance(revision.get("repo"), dict)
                or type(revision["repo"].get("id")) is not int
                or revision["repo"]["id"] != repository.github_repository_id
                or revision["repo"].get("full_name")
                != f"{repository.github_owner}/{repository.github_name}"
            ):
                raise GitHubFailure("Pull request revision or repository changed")
        return str(pull["body"])

    try:
        app_jwt = jwt.encode(
            {
                "iat": int(time.time()) - 60,
                "exp": int(time.time()) + 540,
                "iss": str(settings.github_app_id),
            },
            secret(settings.github_private_key_env),
            algorithm="RS256",
        )
        authorization_check()
        response = await client.post(
            f"https://api.github.com/app/installations/{settings.github_installation_id}/access_tokens",
            headers=GitHubPublisher.headers(app_jwt),
            json={
                "repository_ids": [repository.github_repository_id],
                "permissions": {"pull_requests": "write"},
            },
        )
        if response.status_code != 201:
            raise GitHubFailure("GitHub installation authentication failed")
        token = response.json()["token"]

        async def read() -> tuple[dict[str, Any], str]:
            authorization_check()
            response = await client.get(route, headers=GitHubPublisher.headers(token))
            response.raise_for_status()
            pull = response.json()
            body = checked_body(pull)
            authorization_check()
            return pull, body

        pull, body = await read()
        if confirmed not in body:
            if body.count(previous) != 1:
                raise GitHubFailure("Generated evidence section was changed; reconcile manually")
            replacement = body.replace(previous, confirmed, 1)
            update: dict[str, Any] = {"body": replacement}
            if pull.get("title") == "Agentic Delivery: pending manual acceptance":
                update["title"] = "Agentic Delivery: verified candidate"
            authorization_check()
            try:
                response = await client.patch(
                    route, headers=GitHubPublisher.headers(token), json=update
                )
                response.raise_for_status()
            except httpx.HTTPError:
                pass  # One read-back must confirm the effect; never repeat PATCH here.
            _, body = await read()
        if body.count(confirmed) != 1 or previous in body:
            raise GitHubFailure("Manual acceptance evidence update was not confirmed")
        authorization_check()
        return {
            "status": "CONFIRMED",
            "acceptance_artifact": acceptance_digest,
            "head_sha": publication["head_sha"],
            "manifest_digest": publication["manifest_digest"],
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise GitHubFailure("Manual acceptance publication requires reconciliation") from None
    finally:
        if token:
            with suppress(httpx.HTTPError):
                await client.delete(
                    "https://api.github.com/installation/token",
                    headers=GitHubPublisher.headers(token),
                )
        if owned_client:
            await client.aclose()
