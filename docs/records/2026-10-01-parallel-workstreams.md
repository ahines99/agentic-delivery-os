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

## Repository rules on `main`

Classic branch protection on `main` was replaced by two repository rulesets on 2026-10-01:

- **`main: required checks and history`** (id 24284761). No bypass. It enforces:
  - the four CI checks, with the branch up to date with `main`;
  - linear history;
  - no force pushes and no deletion.
- **`main: human review (owner may bypass via PR)`** (id 24284762). It requires one approval,
  and dismisses stale approvals. The repository admin role may bypass it, but only through a
  pull request.

The owner can now merge their own PRs once CI passes, without temporarily lowering protection.
PRs from the delivery App, which is not a repository admin, still need a human approval.
The App's draft-only publisher and the absence of any merge code path are unchanged. The
protected `delivery-workbench-v2` delivery target keeps its classic protection.
