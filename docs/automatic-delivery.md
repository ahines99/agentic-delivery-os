# Automatic Linear delivery

Create a new issue in the configured Linear team after monitor enrollment. Describe
the behavior and acceptance criteria clearly. Leave it unassigned or assign it to the
configured worker. An optional `Repository: owner/name` or `Repository: name` line
must match the onboarded GitHub repository. Tickets assigned to someone else and
completed/cancelled tickets are skipped.

The local service checks Linear every 30 seconds by default, persists one workflow,
plans the change, automatically approves an eligible low-risk plan, builds and tests
in Docker, obtains independent review, publishes a draft PR, checks GitHub CI and
updates Linear to In Review. The PR stays available for human review and merge.
Ambiguous, high-risk, failed or stale work does not become review-ready.

Configuration:

- Set `automatic_execution: true` on the onboarded repository.
- Set a timezone-aware `linear_poll_start` once, when enabling monitoring; older backlog
  is excluded. Keep the saved `.local/linear-monitor.json` cursor across restarts.
- Configure repository/team/worker/review-state IDs, the model and finite budget,
  a pinned sandbox image, GitHub App credentials and required CI checks.
- Enable publication only after the target base branch contains the expected source
  and CI workflow. Local snapshot configuration must refer to the intended baseline.

After the initial database/runner setup in the [runbook](runbook.md), run:

```sh
uv run --env-file .local/linear.env --env-file .local/model.env delivery-service run --config config.local.json
```

The API stays on loopback port 18090. Detection and CI reconciliation use outbound
provider APIs, so this mode does not require a public tunnel. The existing webhook
gateway can still be used for signed events. The machine must be awake and online.

On Windows, `scripts/run_local_service.ps1` starts the existing Docker Compose services
and supervises this command in a hidden process, restarting it after failure. Register
it as the current user's login task for unattended local operation. It uses a mutex
to prevent duplicate supervisors and writes private logs under `.local/runtime`.
This is a local login service, not an always-on hosted deployment.

Use authenticated `/work-items` and `/workflows/{id}` reads for progress. The monitor
state records the last successful cursor and held source IDs; private service logs
record polling failure types. Editing an already admitted ticket does not silently
start a new budget. Resolve the existing workflow through clarification or rerun.

See [ADR-025](adr/ADR-025-automatic-linear-delivery.md) for the owner-authorized change
from mandatory human plan approval to explicit per-repository automation.
