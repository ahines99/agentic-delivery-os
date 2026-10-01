"""Report delivery progress back to Linear tickets (roadmap DO-4, ADR-037; DO-3, ADR-038)."""

from datetime import datetime
from typing import Any, Literal, NamedTuple

from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.storage.store import NotFound, Store

ACTIVE = frozenset(
    {
        "NEW",
        "INGESTED",
        "ANALYZING",
        "READY",
        "PLANNING",
        "PLAN_REVIEW",
        "IMPLEMENTING",
        "VALIDATING",
        "PR_OPEN",
        "REVIEWING",
        "CHANGES_REQUESTED",
        "ACCEPTANCE_CHECK",
    }
)
BLOCKED = frozenset({"NEEDS_CLARIFICATION", "POLICY_BLOCKED", "FAILED", "CANCELLED"})
MERGED = frozenset({"MERGED", "MERGED_UNVERIFIED"})
MAX_REASON = 500

Status = Literal["in_progress", "in_review", "done", "blocked"]


class Report(NamedTuple):
    status: Status
    key: str
    body: str


def desired_report(run: dict[str, Any], publication: str | None, reason: str) -> Report | None:
    """Map durable workflow and publication state to one ticket report, or none."""
    source = run["work_item"].get("source_system")
    if source not in {"linear", "product_ops"}:
        return None
    identity, state = run["id"], run["state"]
    if state in ACTIVE:
        return Report("in_progress", f"{identity}:in_progress", "Delivery OS: work in progress.")
    if state in BLOCKED:
        detail = " ".join(reason.split())[:MAX_REASON] or state
        return Report(
            "blocked",
            f"{identity}:{run['sequence']}:blocked",
            f"Delivery OS: blocked ({state}). Reason: {detail}",
        )
    if state == "HUMAN_REVIEW" and publication in MERGED:
        return Report("done", f"{identity}:done", "Delivery OS: done. The pull request was merged.")
    if state == "HUMAN_REVIEW" and publication is None and source == "product_ops":
        return Report(
            "in_review",
            f"{identity}:in_review",
            "Delivery OS: in review. The change awaits human review.",
        )
    if state == "HUMAN_REVIEW" and publication == "CLOSED":
        return Report(
            "blocked",
            f"{identity}:closed:blocked",
            "Delivery OS: blocked. The pull request was closed without merging.",
        )
    # In review is reported by the handoff itself (status change and PR attachment).
    return None


def linear_issue(store: Store, run: dict[str, Any]) -> str | None:
    """Linear tickets are the work item itself, or the issue a Product Ops handoff published."""
    if run["work_item"].get("source_system") == "linear":
        return str(run["work_item"]["id"])
    payload = store.inbox_payload(run["id"], "product_ops") or {}
    issue = payload.get("linear_issue_id")
    return issue if isinstance(issue, str) and issue else None


def _reporting(repository: RepositoryConfig) -> bool:
    return bool(repository.linear_team_id and repository.linear_assignee_id)


async def report_progress(
    settings: Settings, store: Store, linear: LinearClient, reported: set[str]
) -> int:
    """Post each report once per ticket; `reported` caches keys already confirmed."""
    since = settings.linear_progress_start
    if since is None:
        return 0
    posted = 0
    for repository in filter(_reporting, settings.repositories):
        latest: dict[str, dict[str, Any]] = {}
        for run in store.list_workflows((repository.id,), limit=200):
            latest.setdefault(run["work_item"]["id"], run)  # newest run per ticket
        for run in latest.values():
            if datetime.fromisoformat(run["updated_at"]) < since:
                continue
            try:
                publication = store.publication(run["id"])["status"]
            except NotFound:
                publication = None
            events = store.events(run["id"], after=run["sequence"] - 1, limit=1)
            reason = events[0]["reason"] if events else ""
            report = desired_report(run, publication, reason)
            if report is None or report.key in reported:
                continue
            issue_id = linear_issue(store, run)
            if issue_id is None:
                continue
            view = await linear.progress_view(issue_id)
            if (view.get("team") or {}).get("id") != repository.linear_team_id or (
                view.get("assignee") or {}
            ).get("id") != repository.linear_assignee_id:
                reported.add(report.key)  # No longer ours to report on.
                continue
            state = view.get("state") or {}
            if (
                report.status == "in_progress"
                and repository.linear_in_progress_state_id
                and state.get("type") in {"backlog", "unstarted"}
            ):
                await linear.move_state(issue_id, repository.linear_in_progress_state_id)
            if (
                report.status == "done"
                and repository.linear_done_state_id
                and state.get("id") != repository.linear_done_state_id
            ):
                await linear.move_state(issue_id, repository.linear_done_state_id)
            if await linear.comment_once(
                issue_id, f"<!-- delivery-progress:{report.key} -->", report.body
            ):
                posted += 1
            reported.add(report.key)
    return posted
