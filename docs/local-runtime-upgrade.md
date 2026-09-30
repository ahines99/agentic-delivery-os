# Local runtime upgrades

## Operation logging and lifecycle metrics (2026-09-30)

The service was upgraded from `f489947` to `4ae54e6` after
[complete hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36761138622)
passed: 3,381 tests and 154 skips per Python version, all 157 service integration
tests, package builds and secret scanning. This installs correlated operation
events, optional lifecycle/cost metrics and the manual-review export correction.

The first script launch was refused by PowerShell execution policy before it ran.
The reviewed script then ran with a process-scoped execution-policy setting. Its
two idle checks passed before/after stopping the verified supervisor and owned
process tree. The clean source checkout fast-forwarded and the existing Windows
task restarted with unchanged private configuration.

At **19:20:40 UTC**, API/database readiness, fresh workflow/activity pollers and an
advancing Linear cursor (**19:20:37.011053 UTC**) were confirmed. All nine workflow
states and both exact handoff bindings were retained. Their digest remains
`c3bccc33e891da90cb82329bbf6ac3cf410ea24a797448929d9e34809b176dd6`.
No active run was interrupted, provider mutation used or PR merged.

The later provider/cleanup diagnostic export and added wall-time/network tests are
newer work with separate verification. They are not installed by this upgrade.
The full Windows suites remain separately tracked; this restart is not a new live
ticket result, human acceptance, or host-loss recovery drill.

## Automatic publication recovery (2026-09-30)

The installed service was upgraded from `6b74944` to `f489947` after its
[complete hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36754579549)
passed all jobs: Python 3.12/3.13 each passed 3,349 tests with 151 skips; the service
job passed all 154 integration tests, including actual publishing-worker process
loss and replacement recovery. Package builds and secret scanning also passed.
The integration marker selection differs from the per-Python default skip selection;
these are separate runs, not additive coverage.

Both the live database and Temporal queue were idle before stopping the verified
supervisor/process tree, and remained idle in the second check before fast-forward.
The unchanged Windows task and private configuration then restarted the service.
At **18:20:49 UTC**, API/database readiness, fresh workflow/activity pollers and the
advancing Linear cursor (**18:20:45.465432 UTC**) were confirmed. All nine workflow
states and both exact PER-13/14 workflow/PR/head bindings were retained; the binding
digest stayed `c3bccc33e891da90cb82329bbf6ac3cf410ea24a797448929d9e34809b176dd6`.
Upgrade verification made no new provider mutation and did not merge a PR.

ADR-032 is now installed. After publication uncertainty, new workflows may confirm
an existing verified draft and resume the ordinary CI/manual/tracker gates. Missing
or conflicting effects remain blocked. This upgrade does not install the newer
`bb56d76` operational-event logging change, whose full verification is separate.
Windows regression at `f489947` remains running. No host reboot, arbitrary surviving
worker fencing or new live ticket result is claimed by this restart.

## Attachment and terminal-command recovery (2026-09-30)

The installed service was upgraded from the `f3bcbc6` application to `6b74944` after
its [complete hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36748606468)
passed: 3,324 tests and 145 skips on each of Python 3.12/3.13, all 145 service
integration tests, package builds and secret scanning. The intervening `acd9a1d`
checkout contained only documentation and a calibration-test fixture correction.

The supervisor and its verified process tree were stopped only after the live
database and Temporal queue showed no active work. A second idle check after stopping
preceded the fast-forward. The existing Windows task then restarted with unchanged
private settings. At **17:37:33 UTC**, readiness and fresh workflow/activity pollers
were confirmed; the Linear cursor advanced to **17:37:29.702971 UTC**. All nine prior
workflow states and both exact PER-13/14 publication bindings were retained. The
before/after binding digest was identical. No new provider mutation was used to
verify the upgrade.

The installed changes reconcile a lost Linear PR-attachment acknowledgement and
preserve an already applied cancellation when its closed-workflow redelivery receives
NOT_FOUND. Full Windows runs remain separately tracked. ADR-032 publication recovery
is newer work and is **not installed** by this upgrade. No reboot or host-loss recovery
was exercised; the existing local hosting requirements still apply.

## Manual acceptance and bounded container lifetime

The local service was upgraded to `f3bcbc64131e29aaff8c96881b7a44df3773cbbd` on
2026-09-30. Its application code, dependencies, scripts and infrastructure are
identical to `430bc19`, whose [complete hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36737373590)
passed 3,304 tests on each Python version, all 130 service integration tests,
package builds and secret scanning. The additional changes were documentation and
six separately passing [admission tests](product-admission-controls.md).

Before the update, the live database and actual Temporal task queue both showed no
active workflows. The restart stopped the existing login supervisor and its verified
owned process tree, fast-forwarded the clean implementation checkout, and restarted
the same Windows task with unchanged private settings and cursor.

At 16:10:22 UTC, post-restart checks confirmed:

- `/readyz` returned ready with a ready database.
- Workflow and activity pollers had access timestamps after the restart.
- The persisted Linear cursor advanced to 16:10:12.982719 UTC.
- The new manual-review read route and existing generic command route were registered;
  unauthenticated access to the manual-review route returned HTTP 403.
- All nine workflow states were retained. A separate metadata-only read verified the
  exact PER-13/14 workflow identities, PR numbers, head revisions and HUMAN_REVIEW /
  DRAFT_HANDOFF states against the recorded handoffs.

The first observer incorrectly expected a dedicated POST OpenAPI route. Correcting
it to the actual generic command route verified the running service without another
restart. Private metadata records retain that distinction; no human decision or
new delivery result was invented to satisfy the check.

The startup uses the existing source checkout through `uv run --no-sync`. A separately
staged non-editable wheel passed CLI and actual Docker preflight checks; that does not
make this service an immutable wheel deployment. Keep the machine and Docker running.

The installed head's [combined CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36740262123)
subsequently passed 3,304 tests per Python version and all 136 service integration
tests, builds and secret scanning. Full Windows feature suites and a subsequent
test-startup fixture correction remain tracked in [implementation status](implementation-status.md). This upgrade
does not close the historical evaluation, complete adversarial/recovery qualification
or human pilot gates, and it performs no merge or production deployment.
