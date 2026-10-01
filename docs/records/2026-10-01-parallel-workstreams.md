# 2026-10-01: Single trunk, parallel-workstream rules, serialized delivery

## What changed

- **Single trunk.** `main` is the only integration branch. PR #1 squash-merged
  `feat/governed-delivery-platform` into `main` (`c9641dc`), and both branches had identical
  trees afterwards. `feat/governed-delivery-platform` is frozen and receives no new PRs. The
  installed service still runs from that checkout until its next supervised upgrade, which
  switches it to `main`.
- **Workflow rules.** `AGENTS.md` and `docs/contributing.md` now require short branches from
  current `main`, merges in order, ADR numbers checked against open PRs, and per-change
  records in this directory.
- **Serialized delivery (ADR-033).** The Linear monitor defers a new ticket or clarification
  edit while its repository has an active run or an unmerged publication.

## Verification

- Monitor tests: 71 passed. Twelve are new:
  - a second ticket stays unclaimed until the first PR merges;
  - a clarification edit waits for another delivery;
  - a table of `delivery_in_progress` states.
- ruff, ruff format, mypy (strict) and the full parallel suite: see the PR checks.

## Not verified

ADR-033 is not installed in the local service and has not run against live Linear tickets.
The repository ruleset that replaces classic branch protection on `main` is recorded in the
PR description, with the command used.
