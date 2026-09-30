# ADR-021: Require program enrollment at evaluation execution entry points

Status: implemented with scoped verification, 2026-09-30. No historical execution or migration.

## Problem

[ADR-020](ADR-020-prospective-program-budget-envelopes.md) enforces shared capacity inside
enrolled ledgers. An execution caller could still supply a legacy ledger to preparation,
calibration or campaign APIs and receive only per-account limits. Admission to the supported
evaluation program must require enrollment, including when resuming an existing account.

## Decision

`EvaluationExecutionStore.require_program_enrollment()` reads the actual local binding and
the matching concrete registry under its current permission guard. The registry identity,
target identity and enrolled target nonce must agree. A legacy ledger, a read-only handle
without the registry, revoked permission or inconsistent binding refuses execution admission.
The check creates no account, registry, enrollment, grant or spending capacity.

Require that check in qualification calibration, deterministic qualification, the qualification
controller, standalone deterministic scoring, synthetic preparation, owned semantic preparation,
semantic calibration, adjudication calibration and canonical campaign allocation. Also require
it in candidate execution, each campaign deterministic scoring operation, historical semantic
scoring and historical adjudication, which can reuse an already allocated account.

Both semantic calibration runners check before selecting a new or resumed plan. Checking only
their account-creation branch would leave a partial legacy plan able to resume execution.
All existing data, model, task, policy, deadline and per-account checks remain required. After
admission, the existing ledger reservation path rechecks the current registry and ACTIVE/OPEN
account before each new model or infrastructure reservation. Admission itself does not imply
available capacity: account creation must still reserve its whole maximum envelope atomically.

## Compatibility and scope

Schema-1 ledgers and their original evidence remain unchanged. Generic ledger primitives
retain their prior behavior for inspection, original settlement and compatibility; they are
not the supported program execution entry points. Current completed-evidence validators and
metadata readers do not require fresh execution enrollment. Calling an execution runner,
including a runner's cached/recovery path, does require it. Use the dedicated completed reader
for historical evidence; do not enroll an old ledger or rewrite a frozen grant to make it run.

This is enforcement within the trusted controller API, not a security boundary against a
trusted administrator invoking lower-level primitives, replacing code or configuring another
registry. Deployment must pin the intended registry and current accounting authority. Test
fixtures explicitly provision owned registries; production never discovers one by filename,
creates one implicitly or uses a test bypass.

The shared registry still excludes historical/pre-registry liabilities and external invoices.
This decision therefore does not establish complete program cost, authorize paid calls, release
unknown liabilities, promote a campaign, or close operational/pilot gates.

## Verification

Admission tests exercise actual registry/ledger bindings, legacy denial, missing and revoked
registry access, exhausted capacity, existing candidate/scoring/semantic/adjudication accounts,
and effect-free completed calibration inspection without registry access. Existing execution
fixtures now use actual enrolled ledgers rather than overriding the admission predicate.
Full execution regression checks and exact-head CI are recorded in the completion audit.
