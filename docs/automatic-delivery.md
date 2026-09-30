# Automatic Linear delivery

Create a new issue in the configured Linear team after monitor enrollment. Describe
the behavior and acceptance criteria clearly. Leave it unassigned or assign it to the
configured worker. An optional `Repository: owner/name` or `Repository: name` line
must match the onboarded GitHub repository. Tickets assigned to someone else and
completed/cancelled tickets are skipped.

Intake checks the latest issue before assignment and rechecks its state after
assignment. A completed, cancelled or already-started issue is not admitted from
a stale discovery result. If an assignment response is lost, one read-back must
confirm the expected worker, issue identity, team, text and eligible state before
intake proceeds. Unconfirmed reads retain the polling cursor; the scan does not
repeat the assignment mutation. These checks observe provider state at read time,
not an atomic lock against subsequent human edits in Linear.

The local service checks Linear every 30 seconds by default, persists one workflow,
plans the change, automatically approves an eligible low-risk plan, builds and tests
in Docker, obtains independent review, publishes a draft PR, checks GitHub CI and
attaches the PR link to the ticket and updates Linear to In Review. The PR stays
available for human review and merge. Link creation uses Linear's
[issue-and-URL idempotency](https://linear.app/developers/attachments), so a repeated
handoff updates the same attachment.
If Linear accepts a review-state update but its response is lost, the adapter makes
one read-back and checks the current ticket before confirming the handoff. An
unconfirmed attachment or unavailable read-back still requires reconciliation.
Ambiguous, high-risk, failed or stale work does not become review-ready.
When a workflow is waiting for clarification, answer by editing the ticket title or
description in Linear. The monitor resumes planning in the same workflow and budget
after verifying the current assignment and text. Other in-flight or completed ticket
edits remain held; they do not silently create another attempt.

Configuration:

- Set `automatic_execution: true` on the onboarded repository.
- Set a timezone-aware `linear_poll_start` once, when enabling monitoring; older backlog
  is excluded. Keep the configured `linear_monitor_state` cursor across restarts
  (default `.local/linear-monitor.json`).
- Configure repository/team/worker/review-state IDs, the model and finite budget,
  a pinned sandbox image, GitHub App credentials and required CI checks. Include
  the supported local lint/format command profiles when those checks are required
  by CI; see [ADR-026](adr/ADR-026-local-quality-checks.md).
- Enable publication only after the target base branch contains the expected source
  and CI workflow. Local snapshot configuration must refer to the intended baseline.

After the initial database/runner setup in the [runbook](runbook.md), run:

```sh
uv run --env-file .local/linear.env --env-file .local/model.env delivery-service run --config config.local.json
```

The API stays on loopback port 18090. Detection and CI reconciliation use outbound
provider APIs, so this mode does not require a public tunnel. The existing webhook
gateway can still be used for signed events. The machine must be awake and online.

Set `github_poll_enabled: true` to also observe managed PRs after handoff without a
webhook. The combined runtime starts `github-monitor`, which checks a bounded page
every `github_poll_seconds` (60 by default). Authenticated
`/workflows/{id}/publication` reports closed, merged or changed-revision outcomes.
This read-only service does not merge PRs, spend model tokens, mark Linear Done or
restore readiness after a PR changes. See [ADR-027](adr/ADR-027-outbound-publication-observation.md).

On Windows, `scripts/run_local_service.ps1` starts the existing Docker Compose services
and supervises this command in a hidden process, restarting it after failure. Register
it as the current user's login task for unattended local operation. It uses a mutex
to prevent duplicate supervisors and writes private logs under `.local/runtime`.
This is a local login service, not an always-on hosted deployment.

Install the current-user task from PowerShell after configuring the service:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File scripts/install_local_service.ps1
```

The execution policy applies only to the task process; the installer does not change
the machine policy or require administrator privileges. Docker Desktop must be running.
Use a dedicated live PostgreSQL database and Temporal task queue. Test databases and
queues must remain separate: test fixtures can contain pending commands and old workflows.

Use authenticated `/work-items` and `/workflows/{id}` reads for progress. The monitor
state records the last successful cursor and held source IDs; private service logs
record polling failure types. Editing an already admitted ticket does not silently
start a new budget. A NEEDS_CLARIFICATION workflow accepts a verified ticket-text edit;
other states require explicit workflow handling or an eligible rerun.

See [ADR-025](adr/ADR-025-automatic-linear-delivery.md) for the owner-authorized change
from mandatory human plan approval to explicit per-repository automation.

Detection follows the bounded outbound polling pattern inspected in the sibling
Agentic Product Ops repository: a durable cursor and overlapping reads reconcile
new tickets. This service adds delivery-specific assignment, authorization and
workflow execution. See the [verified live result](live-automatic-delivery.md).

## Installed local target

The installed service enables both Linear intake and read-only GitHub outcome polling.
The current owner installation maps the Personal Project Portfolio team to
`ahines99/agentic-delivery-os`, using the protected `delivery-workbench-v2` branch and
the bounded `demos/sample_repo` Python source. New tickets can use
`Repository: agentic-delivery-os`. This is the exercised target; installing the App
on all repositories does not automatically configure their source, dependencies,
test commands or CI checks. Each additional target needs that onboarding.

The implementation remains in [PR #1](https://github.com/ahines99/agentic-delivery-os/pull/1).
Delivery to `main` requires its human merge and an explicit target-base configuration
change. Existing attempts retain their original base and configuration.
