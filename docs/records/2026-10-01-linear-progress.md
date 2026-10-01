# 2026-10-01: Linear progress reporting (DO-4)

## What changed

- **Reporter.** `operations/linear_progress.py` reports in progress, done, and blocked with its
  reason on Linear tickets, from durable workflow and publication state. The Linear monitor
  loop runs it every poll.
- **Linear client.** It gained `progress_view`, `comment_once` and `move_state`. Writes are
  marker-idempotent, and a lost response is confirmed with one read, never repeated.
- **Settings.** `linear_progress_start` (opt-in) and the per-repository
  `linear_in_progress_state_id` and `linear_done_state_id`. The state IDs are excluded from
  the execution digest.
- **ADR.** [ADR-037](../adr/ADR-037-linear-progress-reporting.md).

## Verification

`tests/test_linear_progress.py`: 12 passed. The tests cover:

- the reporter staying off until enabled;
- a policy block posted once with its reason, with no duplicate after a restart;
- an in-progress move only from backlog or unstarted;
- a merged PR marking the ticket done;
- an open handoff left alone;
- no writes to a reassigned ticket;
- lost comment responses, both applied and not applied;
- no backfill of runs older than the start setting;
- no reports for non-Linear work.

## Not verified

Not installed in the local service, and not exercised against live Linear. To enable it, set
`linear_progress_start`, and optionally the two state IDs, in `config.local.json`.
