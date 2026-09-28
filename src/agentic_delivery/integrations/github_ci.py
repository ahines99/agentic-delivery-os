"""Read-only installation-token broker for bounded, exact-PR CI reconciliation."""

import re
import time
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from agentic_delivery.config import RepositoryConfig, Settings, secret
from agentic_delivery.integrations.checks import CheckRunObservation, parse_check_run_response
from agentic_delivery.integrations.github import GitHubFailure, GitHubPublisher


class GitHubCIWaiting(GitHubFailure):
    """A required producer's suite is still running; retry within the CI deadline."""


class GitHubCI:
    def __init__(
        self,
        settings: Settings,
        repository: RepositoryConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings, self.repository, self.client = settings, repository, client
        self.suite_evidence: tuple[dict[str, Any], ...] = ()

    async def reconcile(
        self,
        workflow_id: str,
        publication: dict[str, Any],
    ) -> tuple[CheckRunObservation, ...]:
        repo = self.repository
        if not (
            self.settings.github_app_id
            and self.settings.github_installation_id
            and repo.github_repository_id
            and repo.required_checks
        ):
            raise GitHubFailure("GitHub App and required CI producers must be configured")
        if (
            not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", workflow_id)
            or type(publication.get("number")) is not int
            or publication["number"] <= 0
            or any(
                not re.fullmatch(r"[a-f0-9]{40}", str(publication.get(field, "")))
                for field in ("head_sha", "base_sha")
            )
            or not re.fullmatch(r"[a-f0-9]{64}", str(publication.get("manifest_digest", "")))
        ):
            raise GitHubFailure("Invalid CI publication identity")
        client = self.client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, trust_env=False
        )
        token = ""
        prefix = f"https://api.github.com/repos/{repo.github_owner}/{repo.github_name}"
        try:
            app_jwt = jwt.encode(
                {
                    "iat": int(time.time()) - 60,
                    "exp": int(time.time()) + 540,
                    "iss": str(self.settings.github_app_id),
                },
                secret(self.settings.github_private_key_env),
                algorithm="RS256",
            )
            response = await client.post(
                f"https://api.github.com/app/installations/{self.settings.github_installation_id}/access_tokens",
                headers=GitHubPublisher.headers(app_jwt),
                json={
                    "repository_ids": [repo.github_repository_id],
                    "permissions": {"checks": "read", "pull_requests": "read", "contents": "read"},
                },
            )
            if response.status_code != 201:
                raise GitHubFailure("CI installation authentication failed")
            token = response.json()["token"]

            async def get(route: str) -> httpx.Response:
                result = await client.get(prefix + route, headers=GitHubPublisher.headers(token))
                if result.status_code != 200 or len(result.content) > 4 * 1024 * 1024:
                    raise GitHubFailure("CI provider read failed or exceeded bounds")
                return result

            async def validate_pull() -> None:
                pull = (await get(f"/pulls/{publication['number']}")).json()
                marker = (
                    f"<!-- delivery-operation:{workflow_id} "
                    f"manifest:{publication['manifest_digest']} -->"
                )
                if (
                    pull.get("number") != publication["number"]
                    or pull.get("state") != "open"
                    or pull.get("draft") is not True
                    or pull.get("merged") is not False
                    or marker not in (pull.get("body") or "")
                ):
                    raise GitHubFailure("Pull request review identity changed")
                for side, ref in (("head", "agent/" + workflow_id), ("base", repo.base_branch)):
                    data = pull.get(side) or {}
                    remote = data.get("repo") or {}
                    if (
                        data.get("sha") != publication[side + "_sha"]
                        or data.get("ref") != ref
                        or remote.get("id") != repo.github_repository_id
                        or remote.get("full_name") != f"{repo.github_owner}/{repo.github_name}"
                    ):
                        raise GitHubFailure("Pull request revisions changed")
                base = (await get("/git/ref/heads/" + quote(repo.base_branch, safe=""))).json()
                if base["object"]["sha"] != publication["base_sha"]:
                    raise GitHubFailure("Base advanced; CI evidence is stale")

            async def snapshot() -> tuple[CheckRunObservation, ...]:
                assert repo.github_repository_id is not None
                collected: dict[int, CheckRunObservation] = {}
                total: int | None = None
                for page in range(1, 21):
                    response = await get(
                        f"/commits/{publication['head_sha']}/check-runs?filter=all&per_page=100&page={page}"
                    )
                    body = response.json()
                    count, runs = body.get("total_count"), body.get("check_runs")
                    if (
                        type(count) is not int
                        or not 0 <= count <= 2000
                        or not isinstance(runs, list)
                        or len(runs) > 100
                        or (total is not None and count != total)
                    ):
                        raise GitHubFailure("Incomplete or changing CI pagination")
                    total = count
                    for run in runs:
                        item = parse_check_run_response(
                            run, repository_id=repo.github_repository_id
                        )
                        if (
                            item.head_sha != publication["head_sha"]
                            or item.check_run_id in collected
                        ):
                            raise GitHubFailure(
                                "CI snapshot contains duplicate or foreign evidence"
                            )
                        collected[item.check_run_id] = item
                    if len(collected) == total:
                        if "next" in response.links:
                            raise GitHubFailure("CI pagination disagrees with total")
                        return tuple(collected[key] for key in sorted(collected))
                    if len(runs) != 100 or len(collected) > total:
                        raise GitHubFailure("Incomplete CI snapshot")
                raise GitHubFailure("CI pagination exceeded bounds")

            async def suites() -> tuple[dict[str, Any], ...]:
                found: dict[int, dict[str, Any]] = {}
                total: int | None = None
                for page in range(1, 21):
                    response = await get(
                        f"/commits/{publication['head_sha']}/check-suites?per_page=100&page={page}"
                    )
                    body = response.json()
                    count, rows = body.get("total_count"), body.get("check_suites")
                    if (
                        type(count) is not int
                        or not 0 <= count <= 2000
                        or not isinstance(rows, list)
                        or len(rows) > 100
                        or (total is not None and total != count)
                    ):
                        raise GitHubFailure("Incomplete or changing check-suite pagination")
                    total = count
                    for row in rows:
                        suite_id, app_id = row.get("id"), (row.get("app") or {}).get("id")
                        if (
                            type(suite_id) is not int
                            or suite_id <= 0
                            or suite_id in found
                            or type(app_id) is not int
                            or app_id <= 0
                            or row.get("head_sha") != publication["head_sha"]
                        ):
                            raise GitHubFailure("Invalid check-suite identity")
                        found[suite_id] = {
                            key: row.get(key)
                            for key in (
                                "id",
                                "head_sha",
                                "status",
                                "conclusion",
                                "created_at",
                                "updated_at",
                            )
                        }
                        found[suite_id]["app_id"] = app_id
                        if (
                            app_id in {check.app_id for check in repo.required_checks}
                            and row.get("status") != "completed"
                        ):
                            raise GitHubCIWaiting(
                                "Required producer suite is pending or rerequested"
                            )
                    if len(found) == total:
                        if "next" in response.links:
                            raise GitHubFailure("Check-suite pagination disagrees with total")
                        return tuple(found[key] for key in sorted(found))
                    if len(rows) != 100 or len(found) > total:
                        raise GitHubFailure("Incomplete check-suite snapshot")
                raise GitHubFailure("Check-suite pagination exceeded bounds")

            await validate_pull()
            suites_before = await suites()
            first = await snapshot()
            # REST pagination has no transaction. Require two identical bounded reads;
            # persistence additionally rejects webhook generation changes during I/O.
            second = await snapshot()
            suites_after = await suites()
            if first != second or suites_before != suites_after:
                raise GitHubFailure("CI changed during reconciliation")
            suite_ids = {suite["id"]: suite for suite in suites_after}
            for observation in second:
                suite = suite_ids.get(observation.check_suite_id)
                if not suite or suite["app_id"] != observation.app_id:
                    raise GitHubFailure("Check run has no matching authoritative suite")
            await validate_pull()
            self.suite_evidence = suites_after
            return second
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise GitHubFailure("CI reconciliation unavailable; handoff denied") from exc
        finally:
            if token:
                with suppress(httpx.HTTPError):
                    await client.delete(
                        "https://api.github.com/installation/token",
                        headers=GitHubPublisher.headers(token),
                    )
            if self.client is None:
                await client.aclose()
