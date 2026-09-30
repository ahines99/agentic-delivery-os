"""GitHub App publisher. No merge operation, PAT fallback, checkout, or target execution."""

import re
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from agentic_delivery.agents.evidence import validate_manifest
from agentic_delivery.config import RepositoryConfig, Settings, secret
from agentic_delivery.execution.files import protected, safe_path


class GitHubFailure(RuntimeError):
    pass


class GitHubPublisher:
    def __init__(
        self,
        settings: Settings,
        repository: RepositoryConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings, self.repository, self.client = settings, repository, client
        self.prefix = f"/repos/{repository.github_owner}/{repository.github_name}"

    async def publish(
        self,
        workflow_id: str,
        manifest_digest: str,
        *,
        authorization_check: Callable[[], None] | None = None,
        allow_pending_manual: bool = False,
    ) -> dict[str, Any]:
        def guard() -> None:
            if authorization_check is not None:
                authorization_check()

        guard()
        if not (
            self.settings.publication_enabled
            and self.settings.github_app_id
            and self.settings.github_installation_id
        ):
            raise GitHubFailure("GitHub App publication is not configured")
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", workflow_id):
            raise ValueError("Invalid publication operation identifier")
        manifest, candidate = validate_manifest(
            self.settings,
            self.repository,
            workflow_id,
            manifest_digest,
            allow_pending_manual=allow_pending_manual,
        )
        base_sha = manifest["base_sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", base_sha):
            raise GitHubFailure("Invalid base revision")
        changed = manifest["impact"]["changed"]
        entries = []
        for path in changed:
            safe_path(path)
            if protected(path, self.repository.protected_paths):
                raise GitHubFailure("Publication touches a protected path")
            full = (
                f"{self.repository.snapshot_prefix.rstrip('/')}/{path}"
                if self.repository.snapshot_prefix
                else path
            )
            entry = {"path": full, "mode": "100644", "type": "blob"}
            if path in candidate:
                entry["content"] = candidate[path]
            else:
                entry["sha"] = None
            entries.append(entry)
        if not entries:
            raise GitHubFailure("Nothing to publish")
        client = self.client or httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        )
        token = ""
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
            guard()
            token_response = await client.post(
                f"https://api.github.com/app/installations/{self.settings.github_installation_id}/access_tokens",
                headers=self.headers(app_jwt),
                json={
                    "repositories": [self.repository.github_name],
                    "permissions": {"contents": "write", "pull_requests": "write"},
                },
            )
            if token_response.status_code != 201:
                raise GitHubFailure("GitHub installation authentication failed")
            token = token_response.json()["token"]

            async def request(
                method: str,
                route: str,
                body: dict[str, Any] | None = None,
                accepted: tuple[int, ...] = (200, 201),
            ) -> Any:
                # Stop new mutations after revocation. Existing-token reads still
                # reconcile already-issued effects; cleanup must remain possible.
                if method not in {"GET", "HEAD"}:
                    guard()
                response = await client.request(
                    method,
                    "https://api.github.com" + self.prefix + route,
                    headers=self.headers(token),
                    json=body,
                )
                if response.status_code not in accepted:
                    raise GitHubFailure(f"GitHub operation returned HTTP {response.status_code}")
                return response.json() if response.content else {}

            current = await request(
                "GET", "/git/ref/heads/" + quote(self.repository.base_branch, safe="")
            )
            if current["object"]["sha"] != base_sha:
                raise GitHubFailure("Base branch advanced; revalidation required")
            base = await request("GET", "/git/commits/" + base_sha)
            tree = await request(
                "POST", "/git/trees", {"base_tree": base["tree"]["sha"], "tree": entries}
            )
            branch = "agent/" + workflow_id
            marker = f"<!-- delivery-operation:{workflow_id} manifest:{manifest_digest} -->"
            ref = await request(
                "GET", "/git/ref/heads/" + quote(branch, safe=""), accepted=(200, 404)
            )
            if "object" in ref:
                commit = await request("GET", "/git/commits/" + ref["object"]["sha"])
                if commit["tree"]["sha"] != tree["sha"] or marker not in commit["message"]:
                    raise GitHubFailure(
                        "Existing branch conflicts with this publication; reconcile"
                    )
            else:
                # Git object creation has no visible branch effect until the ref is created.
                commit = await request(
                    "POST",
                    "/git/commits",
                    {
                        "message": "Agentic delivery candidate\n\n" + marker,
                        "tree": tree["sha"],
                        "parents": [base_sha],
                    },
                )
                await request(
                    "POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]}
                )
            pulls = await request(
                "GET",
                "/pulls?state=all&head="
                + quote(self.repository.github_owner + ":" + branch, safe="")
                + "&per_page=100",
            )
            existing = [pr for pr in pulls if marker in (pr.get("body") or "")]
            if len(existing) > 1:
                raise GitHubFailure(
                    "Multiple matching pull requests; operator reconciliation required"
                )
            if existing:
                pull = existing[0]
                if pull["head"]["sha"] != commit["sha"]:
                    raise GitHubFailure("PR head changed after verification")
            else:
                pull = await request(
                    "POST",
                    "/pulls",
                    {
                        "title": "Agentic Delivery: pending manual acceptance"
                        if manifest.get("pending_manual_criteria")
                        else "Agentic Delivery: verified candidate",
                        "head": branch,
                        "base": self.repository.base_branch,
                        "draft": True,
                        "body": evidence_markdown(manifest, manifest_digest) + "\n\n" + marker,
                    },
                )
            number = pull.get("number")
            if type(number) is not int or number <= 0:
                raise GitHubFailure("Invalid pull request identity")
            # Creation and list responses can race with a branch update or PR retarget.
            # Re-read the authoritative PR for both first publication and reconciliation.
            pull = await request("GET", f"/pulls/{number}")
            expected_repository = f"{self.repository.github_owner}/{self.repository.github_name}"

            def matches_repository(value: Any) -> bool:
                return (
                    isinstance(value, dict)
                    and value.get("full_name") == expected_repository
                    and (
                        self.repository.github_repository_id is None
                        or value.get("id") == self.repository.github_repository_id
                    )
                )

            head, target = pull.get("head") or {}, pull.get("base") or {}
            if (
                pull.get("number") != number
                or pull.get("state") != "open"
                or pull.get("draft") is not True
                or pull.get("merged") is not False
                or head.get("sha") != commit["sha"]
                or head.get("ref") != branch
                or not matches_repository(head.get("repo"))
                or target.get("sha") != base_sha
                or target.get("ref") != self.repository.base_branch
                or not matches_repository(target.get("repo"))
                or marker not in (pull.get("body") or "")
            ):
                raise GitHubFailure(
                    "Pull request identity, revisions or review state changed; reconcile"
                )
            return {
                "number": pull["number"],
                "url": pull["html_url"],
                "head_sha": head["sha"],
                "base_sha": target["sha"],
                "head_ref": head["ref"],
                "base_ref": target["ref"],
                "repository_id": head["repo"]["id"],
                "repository_full_name": head["repo"]["full_name"],
                "manifest_digest": manifest_digest,
                "draft": pull["draft"],
                "human_merge_required": True,
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise GitHubFailure("Publication outcome unknown; reconcile before retry") from exc
        finally:
            # Expiry is the fallback; a failed revocation never changes publication outcome.
            if token:
                with suppress(httpx.HTTPError):
                    await client.delete(
                        "https://api.github.com/installation/token", headers=self.headers(token)
                    )
            if self.client is None:
                await client.aclose()

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        }


def evidence_markdown(
    manifest: dict[str, Any], digest: str, *, manual_acceptance: str | None = None
) -> str:
    attempt = manifest["attempts"][-1]
    rows = ["| Criterion | Independent execution |", "| --- | --- |"]
    for criterion, evidence in attempt["criteria"].items():
        safe = str(criterion).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")
        rows.append(f"| {safe} | {'PASS' if evidence['passed'] else 'FAIL'} |")
    pending = manifest.get("pending_manual_criteria", ())
    if manual_acceptance is not None and (
        not pending or not re.fullmatch(r"[a-f0-9]{64}", manual_acceptance)
    ):
        raise ValueError("Manual acceptance requires pending criteria and a valid artifact digest")
    for criterion in pending:
        safe = str(criterion).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")
        result = (
            "PASS — authorized human decision"
            if manual_acceptance
            else "PENDING — authorized human acceptance required"
        )
        rows.append(f"| {safe} | {result} |")
    return (
        (
            "## Manual acceptance pending\n\n"
            if pending and not manual_acceptance
            else "## Verified candidate\n\n"
        )
        + f"Base: `{manifest['base_sha']}`\n\nEvidence manifest: `{digest}`\n\n"
        + "\n".join(rows)
        + (
            "\n\nPending manual criteria block review readiness and the Linear handoff."
            if pending and not manual_acceptance
            else ""
        )
        + (f"\n\nHuman acceptance artifact: `{manual_acceptance}`." if manual_acceptance else "")
        + "\n\nIndependent review and isolated checks are recorded in the manifest."
        + "\n\nHuman review and merge are required. No deployment has occurred."
        + "\n\nLimitations: controlled Python scope; static impact analysis is incomplete."
        + " Artifact retrieval requires access to the operator's evidence store."
    )
