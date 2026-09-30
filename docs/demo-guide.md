# Demonstration guide

The installed local service supports automatic Linear-to-GitHub delivery for the bounded
Python sample. The examples below distinguish the exercised product path from offline
fixtures and remaining portfolio evaluation.

## Live automatic delivery

The owner configuration targets `ahines99/agentic-delivery-os`, protected branch
`delivery-workbench-v2`, and source prefix `demos/sample_repo`. The Windows login task
`AgenticDeliveryOS` is installed. Keep the machine awake and online with Docker Desktop
running. See [automatic operation](automatic-delivery.md) and [provider onboarding](provider-onboarding.md)
for initial setup and additional repositories; installing the App alone does not onboard
all repositories.

1. Create a new Backlog issue in the configured Personal Project Portfolio team.
2. Include `Repository: agentic-delivery-os`, a bounded requested behavior and explicit
   acceptance criteria. Leave it unassigned or assign it to the configured worker.
3. The monitor checks every 30 seconds, assigns the issue, and creates one durable workflow.
   An eligible low-risk plan receives an explicit automated approval before isolated
   implementation, independent validation/review and App publication.
4. GitHub checks must pass before the runtime attaches the PR and moves Linear to In Review.
   The PR remains draft for human review and merge. No merge or deployment is automated.
5. If requirements need clarification, edit the ticket text with the missing decision.
   A verified edit resumes the paused workflow with its original budget. Other active or
   completed ticket changes remain held for explicit handling.

Authenticated `/workflows/{id}` provides the state and questions;
`/workflows/{id}/publication` provides PR observation status. The local API is on
`127.0.0.1:18090`. `/readyz` checks database access, not the entire model/worker/toolchain.
The read-only GitHub monitor records later closed/merged/changed-revision outcomes
without a public webhook. It does not mark Linear Done or restore stale readiness.

## Recorded live evidence

| Case | Actual observation |
| --- | --- |
| Clear ticket PER-13 | Automatically created PR #6, passed all four required checks, reached HUMAN_REVIEW, and confirmed Linear In Review with one PR attachment. Three model calls cost $0.215420. |
| Service restart during PER-13 CI wait | Supervisor restarted the service; workflow, publication and spending remained unchanged. |
| Repeated PER-13 publication | Actual App retry reconciled PR #6 with identical base/head/manifest, without a duplicate PR or new model spending. |
| Ambiguous PER-14 | Paused for a missing sorting decision. Editing the ticket caused one applied clarification command, replanning and PR #7 in the same workflow/budget. Final CI/handoff is still pending. |
| High-risk PER-15 | Actual risk-tier-3 assessment and deterministic policy rejection. One planning call cost $0.032940; no approval, builder, reviewer, container or PR. |
| External closure observation | App REST reads recorded retained PRs #2-#5 as CLOSED. PR #6 stayed DRAFT_HANDOFF. This is an owned external-close exercise, not an actual human merge. |

See [the live record](live-automatic-delivery.md) for revisions, workflow IDs, earlier
failures and accounting boundaries. These are owned integration cases, not historical
benchmark scores, general success rates or human productivity measurements.

## Offline fixture intake

From a checkout with Python 3.12 and locked dependencies:

```sh
uv sync --locked --extra dev
uv run delivery demos/sample_tickets/low-risk.json
uv run delivery demos/sample_tickets/ambiguous.json
uv run delivery demos/sample_tickets/high-risk.json
```

Expected states are READY, NEEDS_CLARIFICATION and POLICY_BLOCKED. These fixture commands
use supplied metadata and no credentials, model, Docker build or PR publication. READY
in this interface is not evidence of executed delivery.

For a separate configured development runtime, use the [runbook](runbook.md). Live and
test databases/queues must remain separate. Publication defaults to disabled; provider
credentials stay in private environment files and never enter candidate containers.

## Verification and remaining demonstrations

The source at `c03a945` passed [full hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36664407290),
including both Python versions and real service integrations. Later observer and
clarification changes have focused passing checks and their own current-head CI.
Do not treat that earlier run as proof for later source revisions.

Actual Docker, PostgreSQL and Temporal tests cover named baseline failures, correction,
cancellation, process loss, provenance and provider-fault cases. See
[implementation status](implementation-status.md) and the [completion audit](completion-audit.md)
for each boundary. A controlled failure fixture is not evidence of every real outage.

The portfolio release still requires a qualified historical corpus, frozen paired
execution, independent agent scoring, complete accounting and a reproducible report.
Two separately acquired development tasks are qualified; the original 36 catalog
candidates remain unqualified. No historical campaign or human-benefit measurement is
claimed. Every product merge and pilot signoff remains human.
