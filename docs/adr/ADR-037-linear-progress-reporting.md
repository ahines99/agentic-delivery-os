# ADR-037: Report delivery progress on Linear tickets

Status: accepted, 2026-10-01; implemented as roadmap item DO-4. Not yet installed in the
local service.

## Problem

Delivery state lived only in Delivery OS storage. PER-16 and PER-17 were blocked by policy, but
nothing on the tickets said so. Product Ops (PO-5) and people watching the ticket need claimed,
in-progress, in-review, done and blocked states, with a reason when blocked.

## Decision

The Linear monitor loop runs a progress reporter after intake. For the newest run of each
Linear ticket in a repository with a configured team and worker:

| Workflow state | Report |
| --- | --- |
| Claimed | The assignment itself, as today. |
| Any active state, from `NEW` to `ACCEPTANCE_CHECK` | One "work in progress" comment. If `linear_in_progress_state_id` is set, the ticket moves to that state, but only while it is still in a backlog or unstarted state. |
| `HUMAN_REVIEW` with an open PR | Nothing new. The existing handoff already attaches the PR and sets the review state. |
| `HUMAN_REVIEW` with a merged PR | One "done" comment. If `linear_done_state_id` is set, the ticket moves to that state. |
| `NEEDS_CLARIFICATION`, `POLICY_BLOCKED`, `FAILED`, `CANCELLED`, or a closed PR | One "blocked" comment per blocking event, with the workflow's recorded reason. |

Further rules:

- **Idempotent.** Each comment carries a hidden `delivery-progress` marker. The reporter reads
  the ticket's comments first and never posts a marker twice, even after a restart.
- **Lost responses.** A lost write response is confirmed with one read and never repeated.
  An unconfirmed write fails the cycle and is retried on the next poll.
- **Ownership.** Nothing is written once the ticket has moved to another team or another
  assignee.
- **What a comment contains.** Reasons are the workflow's own recorded strings: policy text,
  lifecycle reasons and criterion IDs. They are never model output or ticket text.
- **Opt-in.** Reporting is off until `linear_progress_start` is set. Runs last updated
  before that instant are not backfilled.
- **Digest.** The state IDs are tracker routing. They are excluded from the execution digest.

## Consequences

- A block like PER-16's becomes visible on the ticket within one poll interval of the
  reporter being enabled.
- PO-5 can read delivery progress from the ticket. Product Ops still treats its own durable
  records as authoritative.
- Comments are the only write when state IDs are not configured, so the feature needs no
  Linear workflow changes to be useful.
