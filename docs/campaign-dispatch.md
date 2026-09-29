# Serial campaign dispatch

`CampaignDispatcher.run_next(...)` connects the local campaign journal to the concrete
single-attempt coordinator. It claims an intent and a durable `DISPATCH` event before
calling the trusted work factory, allocating an account, exporting worker inputs or
invoking a model. A canonical account that already exists cannot enter this fresh-dispatch
path. Each factory supplies one admitted task and configured coordinator; it grants no
additional spending or data access.

## Durable exclusion and current authority

The journal permits only one unfinished dispatch across all campaigns registered in that
same journal. A repeated call cannot execute a recorded dispatch, including after process
exit or loss of the dispatch acknowledgement. There is no lease timeout, automatic reset,
replacement account or inferred permission to retry. An intent recorded before a failed
dispatch transaction can still receive its first dispatch; no work factory runs until that
transaction has committed.

The existing original account, allocation, task, arm, qualification, model, token, money
and deadline checks remain enforced by the coordinator and concrete stage APIs. The
dispatcher also wraps their authority providers with current phase and dispatch checks.
A changed phase decision, expired grant, missing journal or completed dispatch stops
subsequent protected operations. It cannot undo a request already accepted by a provider.
Stage timeout, cancellation and cleanup controls retain their existing behavior.

Repeated checks use a read-only SQLite connection's `PRAGMA data_version` to avoid
reconstructing an unchanged journal on every provider read. Every committed change causes
fresh reconstruction; changes during reconstruction cause refusal. The file identity and
resolved path must remain fixed. Grant equality and expiry are checked on every call,
and a forced full check precedes completion. This is a database-change cache, not a time
window during which revocation may be ignored. It does not authenticate a malicious owner
who controls the entire database and authority providers.

## Optional adjudication

A trusted optional adjudication factory is invoked only for a valid initial disagreement.
It supplies the concrete historical adjudication executor and model broker with the same
ledger, artifact store and frozen model configuration. The existing executor requires its
separate current calibration, exact original-review bindings and one third operation on the
original account/deadline. Its authority providers also retain the dispatch/phase guard.

The dispatch remains active through the third request and exact result validation. The
original outcome and initial review artifacts stay unchanged. `DispatchedAttempt` returns
the original outcome, its artifact, the optional adjudication artifact and the finished
journal event digest. It is not an aggregate success or phase-promotion decision. A missing
adjudication factory leaves disagreement unresolved; it does not implicitly authorize a
third call. Invalid adjudication similarly remains unresolved under the existing rules.

Execution objects constructed within the dispatch have dispatch-scoped guards. After
completion, use the [completed-attempt report reader](completed-attempt-reporting.md) with
fresh report authority to reconstruct final verdicts and complete costs, including the
optional continuation. Do not reuse execution objects to reopen finished dispatches.

## Completion, uncertainty and recovery

A known candidate or deterministic failure can finish its dispatch and retain its original
failed outcome and costs. After concrete validation, the dispatcher records an
`OUTCOME_REFERENCE` and then `DISPATCH_FINISHED`. These two writes reconcile by stable
identities. The journal itself validates metadata order, not the referenced proof; only the
trusted dispatcher or independently validating recovery caller may assert completion.

An exception or cancellation records bounded `UNKNOWN` metadata where possible, with no
private error text. If even that write fails, the committed dispatch still blocks later
execution. `UNKNOWN`, `STOPPED` and an outcome reference alone do not release an active
dispatch. Original reservations, operation records and uncertainty observations remain.

`reconcile_completed(...)` invokes the concrete whole-attempt reader under current report
authority. It requires the exact campaign/ordinal/task/account, an account created after the
dispatch, original completed proof and full known accounting. It can reconcile a lost
completion acknowledgement after the execution or phase window has expired. It performs no
model, sandbox, artifact or spending-ledger mutation; it appends only the missing journal
completion records. Repeating successful reconciliation preserves those original records.

If completed proof is unavailable, the dispatch remains fenced. This API does not infer
that a lost worker or sandbox is quiescent, classify an incident, abandon an incomplete
attempt, release unknown costs or permit a replacement run. Explicit quiescence/abandonment
reconciliation remains a separate operational gate. The fence applies to work managed by
this one pinned journal; it is not a distributed lock across unrelated journals or a defense
against arbitrary execution outside the trusted controller.

## Remaining campaign work

This composes individual A/B attempts and optional adjudication. The bounded
[phase driver](campaign-phase.md) now schedules one already-authorized phase. The
[readiness mapping](adr/ADR-018-prospective-readiness-reporting.md) can be pinned prospectively,
and [selected preparation inventories](campaign-accounting.md) can be reconciled.
All-assignment aggregate reporting, complete preparation-program coverage,
numerical promotion and restricted-pilot decisions remain required. Sealed-case access
retains the journal's ordering/exposure checks and separate current authorization. No
historical campaign, model accuracy, human benefit or complete MVP follows from this API.

Owned tests use actual SQLite transactions, a subprocess exiting immediately after a
dispatch commit, and real coordinator/broker APIs with controlled HTTP responses. Task
qualification, calibration, protected context admission and sandbox execution remain
explicit fixture boundaries. No historical source, paid model calls or real provider
uncertainty reconciliation is exercised by those fixtures.
