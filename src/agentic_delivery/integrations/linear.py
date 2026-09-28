"""Linear GraphQL reads and version-aware status updates through the control plane."""

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
            result = response.json()
            if result.get("errors") or not isinstance(result.get("data"), dict):
                raise ValueError("Linear returned an invalid GraphQL result")
            return dict(result["data"])
        except httpx.HTTPError as exc:
            raise ValueError(
                "Linear provider unavailable; operation requires reconciliation"
            ) from exc
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

    async def set_review_state(
        self, identity: str, state_id: str, *, team_id: str, assignee_id: str
    ) -> None:
        issue = await self.issue(identity)
        if issue["team"]["id"] != team_id or (issue.get("assignee") or {}).get("id") != assignee_id:
            raise ValueError("Issue assignment changed; status update denied")
        if issue["state"]["id"] == state_id:
            return
        result = await self.query(
            "mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) { "
            "issueUpdate(id: $id, input: $input) { success } }",
            {"id": identity, "input": {"stateId": state_id}},
        )
        if result.get("issueUpdate", {}).get("success") is not True:
            raise ValueError("Linear status update was not confirmed")
