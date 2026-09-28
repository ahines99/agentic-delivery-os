# Canonical A/B candidate execution

`CampaignCandidateExecution` connects the shared candidate iteration engine to a
current canonical campaign allocation, the existing evaluation ledger, `StructuredModel`
and the offline Docker runner. It consumes the allocated arm budget and original
attempt deadline. It creates no account, phase promotion, final semantic score or
product readiness record.

The explicit candidate grant binds the allocation/account, campaign ordinal/phase,
original task and qualification, arm configuration, current candidate policy, model
configuration and current execution/preparation settings. Current allocation and
worker-export qualification are checked before and during effects. A supported typed
policy/tool profile binds the current builder/reviewer schemas, exact frozen prompts,
ordinary file edits and offline pytest. Unknown profiles and arm C are refused.

Both A and B receive the same deterministic plan projection from frozen ticket
criteria. There is no additional planner call or unmetered planner answer. A has no
review callback and returns only `BUILD_VERIFIED` after its checks. B uses separate
builder/reviewer contexts and may repair within the frozen arm limit. Neither status
establishes final semantic correctness or benchmark success.

The worker sees original source, captured requirements, the deterministic plan and
its own build/check/review feedback. The adapter never obtains oracle/reference or
final-scoring artifacts for worker context. Qualification budget fields are excluded.
Original tests remain protected. Baseline and subsequent original regression commands
must select explicit frozen nodes; newly declared criterion nodes execute separately.
Every completed test report binds exact command, image, files, operation and a distinct
nonce. Complete call failures can drive correction; collection, setup, malformed-report
and infrastructure errors stop this bounded route.

The first supported context profile is explicitly `full-source-v1`. Model requests
use the actual broker's conservative forecast and existing account reservation; large
contexts or consumed shared capacity are refused before network access. Nothing is
silently truncated and no frozen cap is increased. Qualifying a task does not prove it
fits this profile. A bounded lexical-selection profile requires a separate frozen
contract and A/B parity evidence; it is not implemented by this adapter.

Stable operation IDs and immutable input checkpoints bind each preflight, verification,
builder and reviewer request. Model operations use the production request/receipt
validator, including exact frozen provider/requested model, rate card and token prices.
Returned model identities remain bound to provider observations; aliases are not silently
rewritten to the requested label. Infrastructure operations reserve finite command-plus-cleanup
time and settle measured elapsed cost. All consume one account alongside other attempt stages.
Current authorization is polled while an operation is active, allowing only its exact
reservation. Other unresolved operations prevent execution. Transport uncertainty is
retained rather than reissued under another identity; no automatic transport retries
are enabled even when the frozen arm ceiling would permit them.

Completed resumption checks the sealed exact operation inventory, receipt digests,
input checkpoints and chronology before constructing a runner or replaying a stage.
Cached broker/runner stages must already be settled. Replay currently traverses the
broker cache and therefore still performs its configured credential lookup; it is not
a separate credential-free completed-result reader. An existing input checkpoint with
no operation row is refused, including a process interruption between input recording
and reservation: this slice cannot safely infer or repair that missing history.
Controlled fault injection proves these state-handling paths, not process-crash recovery.

The result seals the available valid final candidate, iteration evidence and exact
operation inventory before any final-scoring use. Normal correction exhaustion retains
the candidate when available and reports `FAILED`; baseline failure may have no changed
candidate. Invalid edits, uncertain operations or changed authority produce no fabricated
sealed success. Existing private model/context/collector/accounting evidence remains
available for investigation. Downstream scoring cannot feed new builder repairs through
this adapter; changed grants or inputs cannot replace its immutable execution/result
checkpoints.

Owned tests replace historical qualification with an explicit controlled boundary.
Model responses come from HTTPX MockTransport through the real StructuredModel and
SQLite ledger; their semantic judgments and fixture token prices are not model-quality
measurements. Actual Docker tests exercise A and B, including B rejection/repair,
fresh regression/criterion checks and cached reruns on a pinned image. Separate tests
cover grant/expiry revocation, uncertainty, duplicate provider identities, malformed
collector bindings, protected edits, shared budget exhaustion, large-context refusal
and missing receipt recovery. No paid model call, historical candidate scoring or
campaign result follows from this evidence.
