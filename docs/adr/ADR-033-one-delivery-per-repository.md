# ADR-033: One automatic delivery per repository at a time

Status: accepted, 2026-10-01; implemented in the Linear monitor. Not yet installed in the
local service.

## Problem

Two eligible tickets for the same repository each planned and built on the same base
snapshot. PER-13 produced PR #6 and PER-14 produced PR #7. Both changed
`demos/sample_repo/customers.py`, so merging #7 left #6 conflicting. A candidate builds from
the snapshot captured during planning (`assessment.snapshot_digest`). Delaying plan approval
alone would therefore still build the waiting ticket on a stale base.

## Decision

The outbound Linear monitor admits a ticket only when its repository has no delivery in
progress. A delivery is in progress when either of these holds:

- Another run for the repository is in any state other than `NEEDS_CLARIFICATION`,
  `HUMAN_REVIEW`, `FAILED`, `CANCELLED` or `POLICY_BLOCKED`.
- A recorded publication for the repository has not been observed as `MERGED`,
  `MERGED_UNVERIFIED` or `CLOSED`. This covers a handed-off draft PR whose run has already
  ended, and a `STALE` PR that is still open.

When the repository is busy:

- **New tickets** are deferred before they are claimed, so a waiting ticket stays visibly
  unassigned in Linear.
- **Clarification edits** to a paused run are deferred too, because re-analysis takes a
  fresh snapshot.
- **The cursor** is held at the earliest deferred ticket version, so the next scans re-read
  it. `MonitorState.deferred` lists the waiting tickets.

Once the earlier PR is merged or closed, the next scan admits the oldest waiting ticket,
which plans against the new base.

Tickets keep their normal eligibility checks, budgets and authority. This decision grants
nothing new. Signed webhook intake and authenticated local submission are not gated: an
operator submitting work directly is choosing the order.

## Consequences

- Delivered PRs for one repository do not conflict with each other. Planning and building
  for that repository become serial; different repositories still proceed in parallel.
- Release depends on observing the earlier PR's outcome. Keep `github_poll_enabled` (ADR-027)
  or signed callbacks on. Without them a merged or closed PR is never observed, so intake
  for that repository stays deferred: it fails closed instead of building on a stale base.
- While a repository is busy, each scan re-reads tickets updated since the earliest
  deferred one. The existing 20-page scan limit bounds that window.
- A ticket waiting for human plan approval holds its repository. Approve or cancel it
  to release the queue.
