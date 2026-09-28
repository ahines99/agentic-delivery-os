"""Linear GraphQL reads and version-aware status updates through the control plane."""

from collections.abc import Callable
from typing import Any

import httpx

from agentic_delivery.config import secret


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
            raise ValueError(
                "Linear provider unavailable; operation requires reconciliation"
            ) from None
        finally:
            if self.client is None:
                await client.aclose()

    async def issue(self, identity: str) -> dict[str, Any]:
        result = await self.query(
            "query Issue($id: String!) { issue(id: $id) { id title description updatedAt "
            "state { id } team { id } assignee { id } } }",
            {"id": identity},
        )
        if not isinstance(result.get("issue"), dict):
            raise ValueError("Linear issue not found")
        return dict(result["issue"])

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
    ) -> None:
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
        if issue["state"]["id"] == state_id:
            return
        if authorization_check is not None:
            authorization_check()
        result = await self.query(
            "mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) { "
            "issueUpdate(id: $id, input: $input) { success } }",
            {"id": identity, "input": {"stateId": state_id}},
        )
        if result.get("issueUpdate", {}).get("success") is not True:
            raise ValueError("Linear status update was not confirmed")
