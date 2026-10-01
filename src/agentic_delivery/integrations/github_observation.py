"""Read-only GitHub App observations, distinct from signed webhook receipts."""

import time
from contextlib import suppress
from typing import Literal

import httpx
import jwt
from pydantic import AwareDatetime, Field, StrictBool

from agentic_delivery.config import RepositoryConfig, Settings, secret
from agentic_delivery.domain.models import Contract
from agentic_delivery.integrations.github import GitHubFailure, GitHubPublisher


class ObservedRepository(Contract):
    id: int = Field(gt=0, strict=True)
    full_name: str


class ObservedRef(Contract):
    sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    ref: str = Field(min_length=1, max_length=300)
    repo: ObservedRepository | None


class PullObservation(Contract):
    number: int = Field(gt=0, strict=True)
    state: Literal["open", "closed"]
    merged: StrictBool
    draft: StrictBool
    updated_at: AwareDatetime
    head: ObservedRef
    base: ObservedRef


async def read_pull(
    settings: Settings,
    repository: RepositoryConfig,
    number: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> PullObservation:
    """Read one configured PR using a repository-scoped, PR-read-only token."""
    if not (
        settings.github_app_id
        and settings.github_installation_id
        and repository.github_repository_id
        and type(number) is int
        and number > 0
    ):
        raise GitHubFailure("GitHub observation identity is not configured")
    owned = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False)
    token = ""
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
        response = await client.post(
            f"https://api.github.com/app/installations/{settings.github_installation_id}/access_tokens",
            headers=GitHubPublisher.headers(app_jwt),
            json={
                "repository_ids": [repository.github_repository_id],
                "permissions": {"pull_requests": "read"},
            },
        )
        if response.status_code != 201:
            raise GitHubFailure("GitHub observation authentication failed")
        supplied_token = response.json()["token"]
        if not isinstance(supplied_token, str) or not supplied_token:
            raise GitHubFailure("Invalid observation token")
        token = supplied_token
        response = await client.get(
            f"https://api.github.com/repos/{repository.github_owner}/{repository.github_name}"
            f"/pulls/{number}",
            headers=GitHubPublisher.headers(token),
        )
        if response.status_code != 200 or len(response.content) > 4 * 1024 * 1024:
            raise GitHubFailure("GitHub observation unavailable or oversized")
        body = response.json()
        # Project provider metadata only; never persist the PR body, patch or links.
        projected = {key: body[key] for key in PullObservation.model_fields}
        for side in ("head", "base"):
            ref = body[side]
            remote = ref["repo"]
            projected[side] = {
                "sha": ref["sha"],
                "ref": ref["ref"],
                "repo": {"id": remote["id"], "full_name": remote["full_name"]}
                if remote is not None
                else None,
            }
        observation = PullObservation.model_validate(projected)
        if (
            observation.number != number
            or observation.base.repo is None
            or observation.base.repo.id != repository.github_repository_id
            or observation.base.repo.full_name
            != f"{repository.github_owner}/{repository.github_name}"
            or (observation.merged and observation.state != "closed")
        ):
            raise GitHubFailure("GitHub observation identity or state mismatch")
        return observation
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise GitHubFailure("GitHub observation could not be validated") from exc
    finally:
        if token:
            with suppress(httpx.HTTPError):
                await client.delete(
                    "https://api.github.com/installation/token",
                    headers=GitHubPublisher.headers(token),
                )
        if owned:
            await client.aclose()
