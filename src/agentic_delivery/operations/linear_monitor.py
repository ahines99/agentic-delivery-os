"""Outbound Linear discovery and owner-configured plan approval for the local runtime."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime

from agentic_delivery.config import Settings, load_settings
from agentic_delivery.domain.models import Contract, WorkItem
from agentic_delivery.integrations.linear import LinearClient, LinearUnavailable
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Conflict, Store, digest_json

logger = logging.getLogger(__name__)


class MonitorState(Contract):
    scope: str
    cursor: AwareDatetime
    observed: int = 0
    held: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()


async def poll_once(settings: Settings, store: Store, linear: LinearClient) -> int:
    enrolled = settings.linear_poll_start
    repositories = {
        repo.linear_team_id: repo
        for repo in settings.repositories
        if repo.linear_team_id and repo.linear_assignee_id and repo.automatic_execution
    }
    if not settings.admissions_enabled or enrolled is None or not repositories:
        return 0
    until = datetime.now(UTC)
    if enrolled > until or not settings.linear_organization_id:
        raise ValueError("Linear monitor enrollment or organization is invalid")
    scope = digest_json(
        {
            "organization": settings.linear_organization_id,
            "enrolled": enrolled.isoformat(),
            "repositories": {team: repo.id for team, repo in repositories.items()},
        }
    )
    since = enrolled
    path = settings.linear_monitor_state
    if path.exists():
        prior = MonitorState.model_validate_json(path.read_text(encoding="utf-8"))
        if prior.scope == scope:
            if prior.cursor > until:
                raise ValueError("Linear poll cursor is in the future")
            since = max(enrolled, prior.cursor - timedelta(minutes=2))
    after = None
    cursors: set[str] = set()
    issues: list[dict[str, Any]] = []
    for _ in range(20):
        result = await linear.query(
            "query DeliveryMonitor($filter: IssueFilter!, $after: String) { "
            "organization { id } issues(first: 50, after: $after, filter: $filter, "
            "orderBy: updatedAt) { nodes { id title description createdAt updatedAt "
            "team { id } assignee { id } state { id type } } "
            "pageInfo { hasNextPage endCursor } } }",
            {
                "after": after,
                "filter": {
                    "team": {"id": {"in": list(repositories)}},
                    "createdAt": {"gte": enrolled.isoformat()},
                    "updatedAt": {"gte": since.isoformat(), "lte": until.isoformat()},
                },
            },
        )
        if result.get("organization", {}).get("id") != settings.linear_organization_id:
            raise AccessDenied("Linear monitor workspace changed")
        connection = result["issues"]
        for issue in connection["nodes"]:
            created = datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
            updated = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
            if (
                issue["team"]["id"] not in repositories
                or not enrolled <= created <= until
                or not since <= updated <= until
            ):
                raise AccessDenied("Linear monitor returned an out-of-scope issue")
            issues.append(issue)
        page = connection["pageInfo"]
        if page["hasNextPage"] is False:
            break
        after = page["endCursor"]
        if not isinstance(after, str) or not after or after in cursors:
            raise ValueError("Linear pagination did not advance")
        cursors.add(after)
    else:
        raise ValueError("Linear scan exceeded its page limit; cursor retained")
    held: list[str] = []
    deferred: dict[str, datetime] = {}

    def defer(identity: str, updated: str) -> None:
        # ADR-033: one delivery per repository at a time. Keep the cursor at or before
        # this version so the next scan reads the ticket again once the repository is free.
        deferred[identity] = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        logger.info("Linear ticket deferred; repository has a delivery in progress")

    for issue in issues:
        repository = repositories[issue["team"]["id"]]
        if issue["state"]["type"] not in {"backlog", "unstarted"}:
            continue
        declared = re.findall(r"(?im)^Repository:\s*([^\r\n]+)", issue.get("description") or "")
        if declared and any(
            name.strip() not in {repository.id, repository.github_name} for name in declared
        ):
            continue
        current = await linear.issue(issue["id"])
        if (
            current.get("id") != issue["id"]
            or current.get("team", {}).get("id") != issue["team"]["id"]
        ):
            raise AccessDenied("Issue identity or team changed during discovery")
        if current["updatedAt"] != issue["updatedAt"]:
            # The next overlapping scan will read the new version.
            continue
        if current.get("state", {}).get("type") not in {"backlog", "unstarted"}:
            continue
        assignee = current.get("assignee") or {}
        if assignee.get("id") not in {None, repository.linear_assignee_id}:
            continue
        probe = WorkItem(
            id=issue["id"],
            source_system="linear",
            title=issue["title"],
            description=issue.get("description") or issue["title"],
            repository=repository.id,
            base_branch=repository.base_branch,
        )
        if store.latest_source_workflow(probe) is None and store.delivery_in_progress(
            repository.id
        ):
            # Defer before claiming, so a waiting ticket stays visibly unassigned.
            defer(issue["id"], issue["updatedAt"])
            continue
        if assignee.get("id") is None:
            try:
                result = await linear.query(
                    "mutation DeliveryAssign($id: String!, $input: IssueUpdateInput!) { "
                    "issueUpdate(id: $id, input: $input) { success } }",
                    {"id": issue["id"], "input": {"assigneeId": repository.linear_assignee_id}},
                )
            except LinearUnavailable:
                # Confirm one uncertain assignment by reading; never repeat the
                # mutation in this scan or treat a lost response as success.
                current = await linear.issue(issue["id"])
                if (current.get("assignee") or {}).get("id") != repository.linear_assignee_id:
                    raise
            else:
                if result.get("issueUpdate", {}).get("success") is not True:
                    raise ValueError("Linear assignment requires reconciliation")
                current = await linear.issue(issue["id"])
        if current.get("id") != issue["id"]:
            raise AccessDenied("Issue identity changed during assignment")
        linear.validate_issue(
            current,
            team_id=issue["team"]["id"],
            assignee_id=repository.linear_assignee_id or "",
            expected_title=issue["title"],
            expected_description=issue.get("description") or issue["title"],
        )
        # Claiming an issue changes updatedAt. Recheck eligibility after the
        # mutation too, so a concurrent completion/cancellation cannot start work.
        if current.get("state", {}).get("type") not in {"backlog", "unstarted"}:
            continue
        item = WorkItem(
            id=issue["id"],
            source_system="linear",
            title=current["title"],
            description=current.get("description") or current["title"],
            repository=repository.id,
            base_branch=repository.base_branch,
        )
        run = store.latest_source_workflow(item)
        if run:
            previous = WorkItem.model_validate(run["work_item"])
            revision = previous.model_copy(
                update={"title": item.title, "description": item.description}
            )
            if revision == previous:
                continue
            if run["state"] == "NEEDS_CLARIFICATION":
                if store.delivery_in_progress(repository.id, exclude=run["id"]):
                    # Re-analysis takes a fresh snapshot; wait for the other delivery.
                    defer(issue["id"], issue["updatedAt"])
                    continue
                payload = {
                    "expected_sequence": run["sequence"],
                    "spec_digest": run["spec_digest"],
                    "item": revision.model_dump(mode="json"),
                }
                store.enqueue_command(
                    run["id"],
                    kind="clarify",
                    actor="linear-monitor",
                    key=digest_json([run["id"], payload]),
                    payload=payload,
                )
            else:
                held.append(item.id)
            continue
        try:
            store.submit(
                item,
                actor="linear-monitor",
                key=digest_json(item.model_dump(mode="json")),
                budget=settings.budget,
                configuration_digest=settings.execution_digest(item.repository),
            )
        except Conflict:
            held.append(item.id)
    state = MonitorState(
        scope=scope,
        cursor=min([until, *deferred.values()]),
        observed=len(issues),
        held=tuple(held),
        deferred=tuple(sorted(deferred)),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return len(issues)


def approve_plans(settings: Settings, store: Store) -> int:
    activities = Activities(settings, store)
    count = 0
    repositories = tuple(repo.id for repo in settings.repositories if repo.automatic_execution)
    for run in store.list_workflows(repositories, limit=1000, state="PLAN_REVIEW"):
        plan = run["result"].get("plan_digest")
        if not isinstance(plan, str):
            continue
        try:
            activities.validate_automatic_plan(run["id"], plan)
        except (ValueError, KeyError, OSError):
            continue
        store.enqueue_command(
            run["id"],
            kind="approve-plan",
            actor="delivery-automation",
            key=f"{run['id']}:{run['sequence']}:approve",
            payload={
                "expected_sequence": run["sequence"],
                "spec_digest": run["spec_digest"],
                "plan_digest": plan,
            },
        )
        count += 1
    return count


async def monitor(config: Path) -> None:
    initial = load_settings(config)
    store = Store(create_database(initial.database_url))
    try:
        while True:
            settings = load_settings(config)
            if settings.database_url != initial.database_url:
                raise ValueError("Monitor database changed; restart required")
            try:
                await poll_once(settings, store, LinearClient())
            except Exception as exc:
                logger.error("Linear polling failed; cursor retained (%s)", type(exc).__name__)
            try:
                approve_plans(settings, store)
            except Exception as exc:
                logger.error("Automatic plan approval failed; retrying (%s)", type(exc).__name__)
            await asyncio.sleep(settings.linear_poll_seconds)
    finally:
        store.engine.dispose()
