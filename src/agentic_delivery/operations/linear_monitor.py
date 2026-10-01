"""Outbound Linear discovery and owner-configured plan approval for the local runtime."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime

from agentic_delivery.config import RepositoryConfig, Settings, load_settings
from agentic_delivery.domain.models import Contract, WorkItem
from agentic_delivery.integrations.linear import LinearClient, LinearUnavailable
from agentic_delivery.integrations.product_ops import admit as admit_product_ops
from agentic_delivery.integrations.product_ops_client import fetch_handoff, handoff_reference
from agentic_delivery.operations.linear_progress import report_progress
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.repository.snapshot import git
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Conflict, NotFound, Store, digest_json

logger = logging.getLogger(__name__)


class MonitorState(Contract):
    scope: str
    cursor: AwareDatetime
    observed: int = 0
    held: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()


def names_repository(repository: RepositoryConfig, description: str) -> bool:
    """Pickup contract v1: a `Repository:` line is required and must name this repository."""
    declared = re.findall(r"(?im)^Repository:\s*([^\r\n]+)", description)
    accepted = {repository.id, repository.github_name, *repository.linear_repository_names}
    return bool(declared) and all(name.strip() in accepted for name in declared)


def carries_pickup_label(repository: RepositoryConfig, issue: dict[str, Any]) -> bool:
    """Pickup contract v1: the opt-in label is a routing signal, never authority."""
    if repository.linear_pickup_label is None:
        return True
    labels = (issue.get("labels") or {}).get("nodes")
    return isinstance(labels, list) and any(
        isinstance(label, dict) and label.get("name") == repository.linear_pickup_label
        for label in labels
    )


async def claim(
    linear: LinearClient,
    issue: dict[str, Any],
    repository: RepositoryConfig,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Assign an eligible ticket to the worker, confirming a lost response with one read."""
    assignee = current.get("assignee") or {}
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
    return current


REVIEW_BRANCH = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}")
COMMIT = re.compile(r"[0-9a-f]{40}")
MERGED = frozenset({"MERGED", "MERGED_UNVERIFIED"})


async def head_merged(repository: RepositoryConfig, head: str) -> bool:
    """True once a local review head is in the base branch; unreadable means not merged."""
    if repository.local_repository is None:
        return False
    try:
        await git(
            "merge-base",
            "--is-ancestor",
            head,
            f"refs/heads/{repository.base_branch}",
            cwd=repository.local_repository,
        )
    except ValueError:
        return False
    return True


async def documentation_review_open(
    store: Store, repository: RepositoryConfig, *, exclude: str | None = None
) -> bool:
    """A finished documentation run holds the repository until its review branch closes.

    The lane leaves a local review branch, not a hosted PR, so ADR-033's publication check
    cannot see it. The review is closed once its head is in the base branch or the branch is
    deleted. Anything unreadable fails closed.
    """
    if repository.local_repository is None:
        return False
    for run in store.list_workflows((repository.id,), limit=100, state="HUMAN_REVIEW"):
        if run["id"] == exclude or run["work_item"].get("work_type") != "documentation_addition":
            continue
        result = run.get("result") or {}
        branch, head = result.get("branch"), result.get("head_sha")
        if (
            not isinstance(branch, str)
            or not REVIEW_BRANCH.fullmatch(branch)
            or not isinstance(head, str)
            or not COMMIT.fullmatch(head)
        ):
            return True
        cwd = repository.local_repository
        try:
            await git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=cwd)
        except ValueError:
            continue  # Branch deleted: the review is closed.
        if not await head_merged(repository, head):
            return True  # Not merged yet, or unreadable.
    return False


async def repository_busy(
    store: Store, repository: RepositoryConfig, *, exclude: str | None = None
) -> bool:
    """ADR-033: an active run, an unmerged PR, or an open documentation review branch."""
    return store.delivery_in_progress(
        repository.id, exclude=exclude
    ) or await documentation_review_open(store, repository, exclude=exclude)


async def prerequisite_merged(settings: Settings, store: Store, identity: str) -> bool:
    """DO-5: a prerequisite counts once it reached HUMAN_REVIEW and its change merged."""
    run = store.workflow(identity)
    if run["state"] != "HUMAN_REVIEW":
        return False
    try:
        return store.publication(identity)["status"] in MERGED
    except NotFound:
        pass
    head = (run.get("result") or {}).get("head_sha")
    if (
        run["work_item"].get("work_type") != "documentation_addition"
        or not isinstance(head, str)
        or not COMMIT.fullmatch(head)
    ):
        return False
    try:
        repository = settings.repository(run["repository"])
    except ValueError:
        return False
    return await head_merged(repository, head)


async def release_ready(settings: Settings, store: Store) -> int:
    """DO-5: queue held handoff starts whose prerequisites merged, one per free repository."""
    released = 0
    for waiting in store.waiting_starts():
        run = store.workflow(waiting["workflow_id"])
        try:
            repository = settings.repository(run["repository"])
        except ValueError:
            continue
        if run["state"] != "NEW" or not repository.automatic_execution:
            continue
        ready = True
        for prerequisite in waiting["depends_on"]:
            if not await prerequisite_merged(settings, store, prerequisite):
                ready = False
                break
        # ADR-033: a release makes the repository busy, so the next item waits its turn.
        if ready and not await repository_busy(store, repository):
            released += store.release_start(run["id"])
    return released


async def pull_handoff(
    settings: Settings,
    store: Store,
    linear: LinearClient,
    repository: RepositoryConfig,
    digest: str,
    issue_id: str,
) -> Literal["admitted", "hold", "stop"]:
    """Fetch, verify and admit a referenced Product Ops handoff (ADR-038, ADR-039).

    "admitted" means this ticket's own work item has been released and it may be claimed.
    "hold" retries on a later scan without claiming; "stop" never claims this version.
    """
    trust = settings.product_ops
    if not digest or trust is None or trust.handoff_base_url is None:
        return "stop"
    if not store.handoff_runs("product_ops", digest):
        if await repository_busy(store, repository):
            return "hold"
        fetched = await fetch_handoff(trust, digest)
        if fetched.status == "unavailable":
            return "hold"
        if fetched.status == "stopped":
            logger.info("Product Ops handoff stopped (%s); ticket not claimed", fetched.reason)
            return "stop"
        try:
            await admit_product_ops(
                fetched.raw,
                expected_digest=digest,
                actor=None,
                settings=settings,
                store=store,
                linear=linear,
            )
        except (AccessDenied, ValueError, KeyError) as exc:
            logger.warning(
                "Product Ops handoff refused (%s); ticket not claimed", type(exc).__name__
            )
            return "stop"
        await release_ready(settings, store)
    own = [
        run
        for run in store.handoff_runs("product_ops", digest)
        if run["linear_issue_id"] == issue_id
    ]
    if not own:
        # The ticket quotes the reference but is not one of the handoff's published tickets.
        return "stop"
    # Product Ops: never claim a ticket only to hold it. Wait for its prerequisites.
    return "admitted" if own[0]["released"] else "hold"


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
        if not names_repository(repository, issue.get("description") or ""):
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
        if not names_repository(
            repository, current.get("description") or ""
        ) or not carries_pickup_label(repository, current):
            continue
        reference = handoff_reference(current.get("description") or "")
        if reference is not None:
            # Product Ops work (DO-3): never normal intake; claim only after admission.
            outcome = await pull_handoff(
                settings, store, linear, repository, reference, issue["id"]
            )
            if outcome == "hold":
                defer(issue["id"], issue["updatedAt"])
            elif outcome == "admitted" and (current.get("assignee") or {}).get("id") in {
                None,
                repository.linear_assignee_id,
            }:
                await claim(linear, issue, repository, current)
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
        if store.latest_source_workflow(probe) is None and await repository_busy(store, repository):
            # Defer before claiming, so a waiting ticket stays visibly unassigned.
            defer(issue["id"], issue["updatedAt"])
            continue
        current = await claim(linear, issue, repository, current)
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
                if await repository_busy(store, repository, exclude=run["id"]):
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
    reported: set[str] = set()
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
                await release_ready(settings, store)
            except Exception as exc:
                logger.error("Handoff release failed; retrying (%s)", type(exc).__name__)
            try:
                approve_plans(settings, store)
            except Exception as exc:
                logger.error("Automatic plan approval failed; retrying (%s)", type(exc).__name__)
            try:
                await report_progress(settings, store, LinearClient(), reported)
            except Exception as exc:
                logger.error("Linear progress report failed; retrying (%s)", type(exc).__name__)
            await asyncio.sleep(settings.linear_poll_seconds)
    finally:
        store.engine.dispose()
