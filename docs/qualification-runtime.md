# Executed deterministic qualification checks

`evaluation.qualification_runtime.run_deterministic_qualification` executes the
deterministic portion of qualification: an actual isolation preflight, then three clean
runs of each baseline/reference and acceptance/regression combination. Its result is
`DETERMINISTIC_CHECKS_PASSED_NOT_QUALIFIED`, with `admitted=false`. It does not invoke a
model, export worker input, admit a historical task or run a campaign.

The Python API takes a frozen `DeterministicRequest`, private input/output artifact
stores, a disjoint worker root, the separate evaluation ledger, and trusted callbacks
for current settings, preparation policy and explicit `RuntimeAuthorization`. The
authorization pins the request, execution configuration, preparation policy, account,
budget, infrastructure rate card and absolute issue/expiry times. Data-use authorization
and permission to execute are distinct inputs. Constructing a grant or account in
untrusted task content cannot grant the controller authority.

The request freezes explicit acceptance and regression node identities. Preparation
rechecks exact patch application, immutable evidence, rights scope and expiry, approved
command profiles, risk and disjoint directories. Only the expected baseline acceptance
call failures are normalized for structural verification; setup/teardown failures,
skips, xfails, collection errors, early exits and unexpected nodes fail the stage.
Reference acceptance and both regression variants must pass all three repetitions.
Each run has a distinct operation ID and collector nonce. The collector's documented
same-interpreter trust limitation remains; this is not hostile-code attestation or
proof of semantic oracle quality.

## Spending, cancellation and restart

The grant must cover the declared batch's worst-case infrastructure reservation at its
configured rate. Each operation then reserves atomically under the account's model,
infrastructure and shared ceilings. This is **not an atomic reservation of all thirteen
operations**: other authorized use of the same account can exhaust its cap between
stages, stopping the batch. No later operation can exceed the remaining account cap.
There is no campaign-wide hierarchy across accounts.

The measured duration uses a monotonic clock around the complete awaited Docker
operation, including cleanup. Infrastructure reservations contain zero model tokens.
Cost is the configured estimate rounded upward to integer microdollars, not a cloud
invoice or a claim that a local Docker job incurred an external charge. Time beyond a
reservation cannot be truncated into success. Failed or cancelled operations without a
returned known outcome retain their full reservation. A known returned test failure
settles its observed infrastructure use before the semantic gate rejects it.

Current controller configuration, admission enablement, data permission, grant identity,
rights expiry, separation from every configured repository and the absolute wall deadline are rechecked at
effect boundaries and polled once per second while work is active. Revocation cancels
the child task and awaits cleanup. Cleanup errors become a sanitized failure, not
successful cancellation. Repeated cancellation cannot detach the retained cleanup task;
the controller continues awaiting it. A process crash or host failure can still leave
unknown state; no automatic retry or cleanup claim follows.

The account has an immutable request/grant checkpoint. Per-operation bindings also pin
the prepared inputs, stage, timeout ceiling and rate. Settled runs are recovered from
their recorded receipts and checked again against the frozen collector contract; no
new Docker call is made. An unknown reservation prevents reissuing that operation.
Changing the grant, inputs or clock deadline cannot restart the same account as fresh
work. Only the final complete, validated matrix produces a completion checkpoint. The read-only
`validate_deterministic_evidence` API rechecks that checkpoint, preparation, current authority,
all thirteen ledger settlements, measured rate arithmetic and the complete collector matrix.
This stage validator requires the original execution grant to remain within its wall deadline.
A future durable admission gate needs a separate historical-execution check at the trusted
completion-checkpoint time, plus current rights/configuration/calibration/admission checks; it
must not obtain historical acceptance by substituting an arbitrary past clock.

All detailed execution receipts, stdout/stderr, source, oracle and reference material
remain evaluator-only. The return value contains only status, account and artifact
reference. Exceptions crossing this API are sanitized. Stores and the ledger's trusted
writer remain part of the control-plane boundary; hashes are not external attestation.

## Recorded verification

Thirty controlled tests passed for the full matrix, exact cache reuse, provider-style
lost settlement acknowledgement, malformed collector evidence, changed authority,
expiry, repeated cancellation, cleanup failure, retained unknown reservations, read-only complete-chain
validation and cross-repository scope rejection.
An actual Docker test passed all twelve synthetic checks and the preflight in 20.95
seconds, verified execution/accounting references, and verified that resume performed
no new Docker execution. These synthetic fixtures do not establish historical rights,
real agent calibration, benchmark qualification or a successful campaign.

The remaining qualifier controller must combine these results with verified development
calibration, independent protected semantic reviews and current authorization. Existing
v1 admission records are not automatically converted to a new execution protocol.
