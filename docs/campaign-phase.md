# Bounded phase execution

`CampaignPhaseDriver.run_phase(...)` schedules the frozen ordinals of one already-opened,
currently authorized campaign phase through the concrete [serial dispatcher](campaign-dispatch.md).
The caller supplies the campaign artifact store, trusted work/adjudication factories and a
finite positive `max_attempts` bound. The driver does not open phases, renew grants, create
budgets or alter the schedule. Current admission, calibration, source access, model limits,
runtime checks and original deadlines remain obligations of the concrete attempt executors.

The driver pins the original phase authorization for its whole invocation. A replacement,
expiry or revocation stops progression even if the replacement would independently be valid.
All original phase assignments, including stability attempts, retain their frozen order.
The driver stops before the next split and never opens sealed cases under a development or
validation authorization. A separately authorized test phase retains the journal's existing
sealed-opening and exposure checks.

## Restart and stopping

An invocation may finish all pending assignments or stop after its finite attempt limit.
Reentry reads the journal and schedules the next pending ordinal without repeating completed
dispatches. An intent saved before its first dispatch can take that first dispatch using its
original identity and original grant. An unfinished dispatch stops the driver before invoking
the execution boundary, even if UNKNOWN or an outcome reference was subsequently recorded.
Explicit completed-proof reconciliation must finish that dispatch before scheduling resumes.
Cancellation propagates through the dispatcher; there is no automatic retry or replacement.

Known failed candidates can finish their dispatch and allow the next frozen assignment.
Unknown execution, missing completion acknowledgement, invalid authority or inconsistent
journal state stops the invocation. The journal retains completed work even if authority
expires between an attempt finishing and this driver's progress response.

## Progress is scheduling metadata

`PhaseDispatchProgress` binds the original authorization digest, phase and final journal
sequence/event digest. It separately lists all assigned ordinals, recorded closed ordinals,
finished dispatches and dispatches completed during this invocation. A recorded pre-execution
STOPPED observation may close an ordinal without producing a finished dispatch; these lists
make that distinction visible. `NO_PENDING_ASSIGNMENTS` describes the frozen scheduling queue.
It is not a claim that every candidate passed, every cost is known or the phase may be promoted.

Aggregate correctness, readiness and complete cost reporting still require concrete current
proof consumers, preparation-account reconciliation and explicit frozen readiness mapping.
Numerical promotion, operational controls and human pilot signoff remain separate gates.

## Verification scope

Sixteen owned tests exercise actual journal transactions with a substituted single-attempt
boundary: full phase ordering, stopping before validation, bounded resume, an intent-only
crash, active uncertainty, pre-execution stopped records, expiry, changed authority and false
completion acknowledgements. A seventeenth test invokes the real dispatcher, coordinator and
controlled broker for a known candidate failure and verifies the finite invocation limit.
Together they passed in 37.29 seconds. Admission and runtime remain owned fixture boundaries;
these tests make no historical campaign or real-provider execution claim.
