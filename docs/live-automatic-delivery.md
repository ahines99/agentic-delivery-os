# Live automatic delivery verification

Owned integration exercise, 2026-09-30 UTC. This is a bounded product demonstration,
not a historical benchmark or a claim that all portfolio release gates have passed.

## Current run

[PER-13](https://linear.app/personal-portfolio-project/issue/PER-13/add-ordered-customer-id-helper)
was created unassigned. The outbound monitor detected and assigned it, persisted one
workflow, and recorded an applied `delivery-automation` plan approval. The builder
produced a candidate that passed 10 tests, Ruff lint, Ruff formatting and independent
review on its first attempt. Five criteria have independent execution evidence.
The GitHub App created [PR #6](https://github.com/ahines99/agentic-delivery-os/pull/6).

The workflow reached **`HUMAN_REVIEW` at 2026-09-30 04:04:04 UTC**. Actual provider
readback confirmed Linear **In Review**, exactly one PR attachment, and a ready handoff
with tracker status `CONFIRMED`. The runtime performed the transition; no manual plan
approval, code repair, PR attachment or review-state update was used for this ticket.

[PR #6 CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36664574805)
passed all four required checks at the exact head below: Python 3.12 and 3.13 each
passed 3,100 tests with 111 explicit integration skips; the service job independently
passed all 111 integration tests, and secret scanning passed. The newer runtime
[implementation CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36664407290)
passed 3,114 tests with 114 skips on each Python version, 114 service tests and secret
scanning. These are separate revisions and runs, not additive test counts.

| Binding | Value |
| --- | --- |
| Runtime source | `c03a94506ee97601a59f0dac4722536ea38e64a4` |
| Workflow | `f7a5f818-094c-4b37-a1db-4eaa0855ba40` |
| Repository | `ahines99/agentic-delivery-os` |
| Target | `delivery-workbench-v2`, source prefix `demos/sample_repo` |
| Base | `cbba076268c4b70976e27d22585383547656a02d` |
| PR head | `a1e5040de2842732126bb70d7be7e3376571da83` |
| Manifest | `ff2493a5bd1b3876251c06a7042953ff30805ad0307d51bb2c6a2649212e70c5` |
| Model ledger | Three settled operations, 215,420 microdollars, no reservation |

The publisher is `app/ahines99-agentic-delivery-os`. Tokens are restricted to the
configured repository. Both the target branch and `main` require four checks and
human review with administrator enforcement. No merge or deployment occurred.
Private plans, code-generation records, credentials and manifests remain local;
the table exposes only identifiers and accounting metadata.

## Actual recovery check

The service process was interrupted during this run's CI wait. The Windows login
supervisor restarted it automatically. The API and monitor resumed, and Temporal
completed subsequent `reconcile_ci` activities at 03:36:53 and 03:37:25 UTC.
The workflow ID, sequence, candidate head and spending were unchanged. There was
still one attempt, three model operations and one publication for this ticket.
No candidate container remained. This proves this specific recovery point, not
recovery from every in-flight provider or infrastructure failure.

## Retained earlier attempts

| Ticket | Observed result | Settled model microdollars |
| --- | --- | ---: |
| PER-9 | Windows snapshot failure before model spending; an audited retry produced PR #2, later superseded after a baseline CI test race was found. | 262,750 |
| PER-10 | Initial plan required manual verification; guidance was corrected and an audited retry produced PR #3 on the superseded baseline. | 276,455 |
| PER-11 | Automatic review/correction produced PR #4; GitHub lint failed. | 668,530 |
| PER-12 | PR #5 passed local behavioral checks but failed GitHub lint. | 179,200 |
| PER-13 | PR #6 passed local verification, independent review and all four GitHub checks; Linear In Review and the PR attachment were confirmed automatically. | 215,420 |

PRs #2 through #5 were closed, and their workflows retained as failed or cancelled.
They were never reported as review-ready. The isolated live database retains
1,602,355 settled model microdollars across these tickets, with no unsettled operation.
This is model accounting for this exercise, not total infrastructure or project cost.
An earlier unexecuted receipt remains in the old test database; the live service now
uses a separate database and queue.

The fixes were Windows environment-name handling, test/live database separation,
explicit worker-start synchronization in the runtime test, supported planner
verification guidance, and [local quality checks](adr/ADR-026-local-quality-checks.md)
inside the existing bounded repair loop. No failing check was bypassed.

See [automatic delivery](automatic-delivery.md) for operation and supported scope.

## Outbound publication observation follow-up

The concrete GitHub App read-only observer subsequently reconciled all five retained
product PRs into the live database: #2?#5 are CLOSED and #6 remains DRAFT_HANDOFF.
The observer uses only Pull requests read permission, persists metadata with
`github-rest` provenance and leaves workflow states/spending unchanged. No public
webhook, PR mutation or model call was involved. The live record proves closure
readback; merged and changed-head cases are exercised with controlled HTTP responses,
not an actual human merge. See [ADR-027](adr/ADR-027-outbound-publication-observation.md).

## Linear clarification follow-up

PER-14 (`c38a4485-7ddb-41f1-b470-e02dc50e6b77`) deliberately omitted a required sorting
direction. Actual planning reached NEEDS_CLARIFICATION at 2026-09-30 04:24:24 UTC,
with 61,370 settled model microdollars and no reservation. No candidate was built.
The owned test ticket was then edited to specify ascending order. The monitor
recorded one APPLIED `clarify` command under `linear-monitor`; the same workflow
resumed ANALYZING at 04:25:39 UTC, changing its specification digest while retaining
its original budget and spending. No operator API clarification or new attempt was
used. Completion of the revised delivery is tracked separately from this pause/resume
proof. [ADR-028](adr/ADR-028-linear-clarification-edits.md) defines the narrow behavior.

## Sensitive-work admission follow-up

[PER-15](https://linear.app/personal-portfolio-project/issue/PER-15/controlled-admission-case-sensitive-authentication-changes)
requested sensitive authentication, authorization and production secret-management
changes as an owned negative integration case. Workflow
`a96eb0c6-8e76-42b0-9643-b1b4b76364f9` reached POLICY_BLOCKED at
2026-09-30 04:29:59 UTC. Its assessed risk tier was 3; the deterministic intake policy
independently returned denied. The ledger contained one settled planning operation,
32,940 microdollars and zero reservation. Only the start command existed: no automatic
plan approval, builder/reviewer operation or publication. No workflow-labelled
container remained. Actual Temporal history contained only projection, start-command
disposition and one analyze activity; no candidate, publish, CI or handoff activity
was scheduled. This proves this bounded source/risk case, not detection of every
sensitive request or newly sensitive candidate diff.

An actual repeated publication of PER-13 also reconciled existing PR #6 with identical
base/head/manifest and unchanged model spending. No new PR was created. This proves
that concrete retry; arbitrary lost-response and concurrent provider races remain
separate qualification cases.
