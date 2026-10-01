"""Linear GraphQL reads and version-aware status updates through the control plane."""

import re
from collections.abc import Callable
from typing import Any

import httpx

from agentic_delivery.config import secret


class LinearUnavailable(ValueError):
    """A transport failure leaves the provider's operation outcome uncertain."""


class LinearClient:
    def __init__(
        self, api_key_env: str = "LINEAR_API_KEY", client: httpx.AsyncClient | None = None
    ):
        self.api_key_env, self.client = api_key_env, client

    async def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        client = self.client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, trust_env=False
        )
        try:
            response = await client.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": secret(self.api_key_env)},
                json={"query": query, "variables": variables},
            )
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError:
                raise ValueError("Linear returned an invalid GraphQL result") from None
            if (
                not isinstance(result, dict)
                or result.get("errors")
                or not isinstance(result.get("data"), dict)
            ):
                raise ValueError("Linear returned an invalid GraphQL result")
            return dict(result["data"])
        except httpx.HTTPError:
            raise LinearUnavailable(
                "Linear provider unavailable; operation requires reconciliation"
            ) from None
        finally:
            if self.client is None:
                await client.aclose()

    async def issue(self, identity: str) -> dict[str, Any]:
        result = await self.query(
            "query Issue($id: String!) { issue(id: $id) { id title description updatedAt "
            "state { id type } team { id } assignee { id } labels { nodes { name } } } }",
            {"id": identity},
        )
        if not isinstance(result.get("issue"), dict):
            raise ValueError("Linear issue not found")
        return dict(result["issue"])

    async def _linked_issue(self, identity: str, url: str) -> dict[str, Any]:
        """Reconcile an uncertain attachment write with one bounded provider read."""
        result = await self.query(
            "query DeliveryAttachment($id: String!, $url: String!) { "
            "issue(id: $id) { id title description state { id } team { id } assignee { id } } "
            "attachmentsForURL(url: $url, first: 100) { "
            "nodes { id url archivedAt issue { id } } pageInfo { hasNextPage } } }",
            {"id": identity, "url": url},
        )
        issue, connection = result.get("issue"), result.get("attachmentsForURL")
        if not isinstance(issue, dict) or issue.get("id") != identity:
            raise ValueError("Linear attachment issue was not confirmed")
        if not isinstance(connection, dict):
            raise ValueError("Linear pull request link was not confirmed")
        nodes, page = connection.get("nodes"), connection.get("pageInfo")
        if (
            not isinstance(nodes, list)
            or len(nodes) > 100
            or not isinstance(page, dict)
            or page.get("hasNextPage") is not False
        ):
            raise ValueError("Linear pull request link was not confirmed")
        matches = 0
        for node in nodes:
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("id"), str)
                or not node["id"]
                or node.get("url") != url
                or "archivedAt" not in node
                or not isinstance(node.get("issue"), dict)
                or not isinstance(node["issue"].get("id"), str)
            ):
                raise ValueError("Linear pull request link was not confirmed")
            if node["issue"]["id"] == identity and node["archivedAt"] is None:
                matches += 1
        if matches != 1:
            raise ValueError("Linear pull request link was not confirmed")
        return dict(issue)

    @staticmethod
    def validate_issue(
        issue: dict[str, Any],
        *,
        team_id: str,
        assignee_id: str,
        expected_title: str | None = None,
        expected_description: str | None = None,
    ) -> None:
        """Bind live assignment and supplied ticket semantics before any external handoff."""
        team, assignee = issue.get("team"), issue.get("assignee")
        if (
            not isinstance(team, dict)
            or team.get("id") != team_id
            or not isinstance(assignee, dict)
            or assignee.get("id") != assignee_id
        ):
            raise ValueError("Issue assignment changed; status update denied")
        title = issue.get("title")
        description = issue.get("description") or title
        for actual, expected in (
            (title, expected_title),
            (description, expected_description),
        ):
            if expected is not None and (
                not isinstance(actual, str) or actual.strip() != expected.strip()
            ):
                raise ValueError("Issue specification changed; handoff denied")

    async def set_review_state(
        self,
        identity: str,
        state_id: str,
        *,
        team_id: str,
        assignee_id: str,
        expected_title: str | None = None,
        expected_description: str | None = None,
        authorization_check: Callable[[], None] | None = None,
        pull_request_url: str | None = None,
    ) -> None:
        if pull_request_url is not None and not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*",
            pull_request_url,
        ):
            raise ValueError("Invalid GitHub pull request URL")
        if authorization_check is not None:
            authorization_check()
        issue = await self.issue(identity)
        self.validate_issue(
            issue,
            team_id=team_id,
            assignee_id=assignee_id,
            expected_title=expected_title,
            expected_description=expected_description,
        )
        if pull_request_url is not None:
            if authorization_check is not None:
                authorization_check()
            # Linear upserts by (issueId, URL), including after a lost response.
            try:
                attachment = await self.query(
                    "mutation DeliveryPullRequest($input: AttachmentCreateInput!) { "
                    "attachmentCreate(input: $input) { success } }",
                    {
                        "input": {
                            "issueId": identity,
                            "url": pull_request_url,
                            "title": "Delivery pull request",
                            "subtitle": "Human review and merge required",
                        }
                    },
                )
            except LinearUnavailable:
                # Do not repeat the mutation. Require the exact issue/URL link and
                # fresh ticket semantics before proceeding to the status update.
                if authorization_check is not None:
                    authorization_check()
                issue = await self._linked_issue(identity, pull_request_url)
                if authorization_check is not None:
                    authorization_check()
                self.validate_issue(
                    issue,
                    team_id=team_id,
                    assignee_id=assignee_id,
                    expected_title=expected_title,
                    expected_description=expected_description,
                )
            else:
                if attachment.get("attachmentCreate", {}).get("success") is not True:
                    raise ValueError("Linear pull request link was not confirmed")
        if issue["state"]["id"] == state_id:
            return
        if authorization_check is not None:
            authorization_check()
        try:
            result = await self.query(
                "mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) { "
                "issueUpdate(id: $id, input: $input) { success } }",
                {"id": identity, "input": {"stateId": state_id}},
            )
        except LinearUnavailable:
            # One read can confirm an accepted update whose response was lost.
            # Do not repeat the mutation or infer success from a transport error.
            if authorization_check is not None:
                authorization_check()
            observed = await self.issue(identity)
            self.validate_issue(
                observed,
                team_id=team_id,
                assignee_id=assignee_id,
                expected_title=expected_title,
                expected_description=expected_description,
            )
            if observed.get("state", {}).get("id") != state_id:
                raise
            return
        if result.get("issueUpdate", {}).get("success") is not True:
            raise ValueError("Linear status update was not confirmed")
