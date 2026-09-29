# Completed attempt reporting

`validate_completed_attempt_consumption(task, authority=...)` connects retained
single-attempt coordinator outcomes to the existing read-only candidate, deterministic
and semantic consumers. It reconstructs candidate failures, deterministic failures,
initial semantic results and an optional separately authorized adjudication continuation.
It neither executes a stage nor creates an attempt, spending capacity or replacement result.

## Authority and provenance

`AttemptConsumptionAuthorization` has the fixed purpose `campaign-report`, a window of
at most 24 hours, the exact original outcome artifact and digests of the relevant current
candidate, scoring and semantic consumption grants. The current enabled policy approves
that exact authorization on the pinned execution ledger. Providers are checked before and
after reconstruction. Original execution permission remains historical; current qualification,
data, calibration and consumption access are still required by the corresponding consumers.
Expired original execution windows are never reopened or evaluated with fabricated clocks.

The reader reconstructs the original coordinator binding from the admitted task, frozen
campaign, allocation, model configuration, source commit, preparation policy and artifact
store. Source identity retains the coordinator's trusted-caller attestation boundary; it
is not a measurement of the running interpreter's checkout. The original candidate,
scoring and semantic terms must match their saved checkpoints, including the original
semantic context policy. Original checkpoints and operations must occur in stage order,
with the original outcome completed and checkpointed before the original deadline.

The deterministic document must match the independently reconstructed evidence digest
and the same account, allocation, task and candidate. Semantic proof is reconstructed
through the completed semantic consumer, including exact calibration and the receipt
chain. A current grant cannot legitimize a changed outcome, missing operation or
inconsistent original totals. The reader rereads lower chains, semantic authority,
accounting and observed checkpoints before returning.

## Failures, adjudication and accounting

A candidate failure returns a retained `FAIL` without requiring or invoking deterministic
or semantic work. A deterministic failure similarly requires no semantic calls. Unexpected
later checkpoints or operations are rejected. Every valid report preserves its original
campaign ordinal and all recorded model and infrastructure costs and tokens.

An adjudication must be the one exact continuation accepted by the semantic consumer,
on the same original account and deadline. Its plan must follow the coordinator's original
outcome checkpoint. The report embeds that original outcome unchanged and separately
returns the adjudicated verdict, result reference and complete operation/cost inventory.
Original prefix costs are independently reconstructed; the later operation cannot be
silently omitted or charged to a different attempt.

Unavailable proof, unknown usage, expired access or inconsistent records raise a sanitized
`AttemptInspectionFailure`. They do not become scored failures, free operations or permission
to retry. A campaign aggregate must retain their assignments with unavailable evidence and
incomplete accounting; this reader does not invent those aggregate dispositions.

## Meaning and limits

`ValidatedCompletedAttempt.strict_success` is the reconstructed candidate-level result
from successful deterministic evidence and a valid final semantic pass. It is distinct from
the coordinator's original `strict_success=false` composition marker. The report retains
`execution_authorized`, `phase_promoted` and `campaign_complete` as false.

The report exposes the original arm and candidate status (`BUILD_VERIFIED`, `REVIEW_APPROVED`
or `FAILED`). It does not infer the system's declared readiness from the final score or
assert a false-ready rate. Separate [reporting components](campaign-reporting.md) provide the
frozen readiness mapping, assigned denominators, journal composition and numeric observations;
complete promotion remains open. No human
benefit, historical accuracy, campaign promotion or completed MVP follows from this API.

The version-2 consumption report additionally exposes the actual validated
`acceptance_passed` and `regression_passed` values, with nulls when candidate failure
prevented scoring. The deterministic consumer requires complete, exact original test
collection and valid setup/call/teardown evidence before reporting either a pass or an
assertion failure. These fields do not classify incomplete runs as regressions.
`execution_started_at` comes from the original allocation; `final_completed_at` is the
verified coordinator outcome checkpoint or exact adjudication result checkpoint. Their
difference is elapsed wall time, not CPU or human effort. Original execution outcomes,
grants and cost records retain their original schemas and bytes.

The [aggregate report](campaign-reporting.md) uses these fields only under its current
concrete readers and original prospective statistical policy. Legacy pinned policies
cannot acquire new statistical rules retrospectively.

Owned tests compose actual coordinator, broker and SQLite receipts with controlled HTTP
responses. Qualification, calibration, context admission and sandbox execution are explicit
fixture boundaries. They make no paid calls and inspect no historical source or solutions.
