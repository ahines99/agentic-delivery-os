# Local runtime upgrades

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
