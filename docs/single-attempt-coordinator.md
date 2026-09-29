# Single-attempt execution coordinator

`CampaignAttemptCoordinator.run(task)` composes the existing canonical allocator,
A/B candidate executor, protected deterministic scorer and two initial semantic
scorers for one assigned ordinal. It uses the frozen campaign's protocol and the
one original account, budget and deadline. It does not schedule other ordinals,
advance phases, adjudicate disagreements, publish results or complete a campaign.

The constructor requires concrete allocator/model/calibration dependencies and
explicit current providers for every execution and consumption authorization.
Providers belong to the trusted caller. A provider may obtain a newly supplied
decision once a stage's exact digests exist; the coordinator never constructs an
authorization, expands its scope or adds capacity. Unavailable authority stops
before the dependent execution. Earlier stages and allocated capacity remain
recorded; this is not converted into an ordinary scored failure.

The caller supplies an `AttemptExecutionIdentity` whose source commit and model
configuration must match the frozen campaign and arm. This is a trusted execution
identity attestation. Comparing a commit string does not establish which source
files the process loaded; the caller must establish that correspondence before
providing the identity. Settings, preparation policy, current qualification,
qualification calibration and final-scorer calibration retain their existing
independent checks and scopes.

The order is fixed:

1. Allocate or reconstruct the canonical account. Seal the coordinator binding
   to the exact campaign, ordinal, arm, task, source snapshot, settings, policy,
   qualification, calibration, execution identity and original deadline.
2. Seal the supplied candidate terms and execute A or B. Validate its sealed
   result with the existing effect-free candidate reader under current scoring
   consumption authority. This reader is used on every completed-stage resume;
   the builder is not re-entered after scoring starts.
3. For a successful candidate stage, seal the supplied scoring terms. Execute the
   existing metered preflight, acceptance and regression operations, then
   reconstruct and seal their deterministic document. Current deterministic
   consumption authority is required before advancing.
4. Only after passing deterministic evidence, seal the explicit semantic terms
   and invoke the two-scorer executor. It retains its separate contexts, calibrated
   configuration, shared account reservations and immutable operation identities.
5. Seal an `AttemptOutcome` from the reconstructed stage proofs, exact operation
   receipt inventory, known settled usage and original chronology. The completed
   reader repeats this reconstruction without artifact/ledger writes, key lookup,
   Docker or model calls.

Candidate failure and deterministic failure produce distinct retained `FAIL`
outcomes; neither invokes final semantic models. Two agreeing semantic judgments
produce a scoped agreement outcome. Disagreement or an invalid review produces
`UNRESOLVED`; no replacement or adjudication call is inferred. All outcomes have
`strict_success`, `phase_promoted`, `campaign_complete` and
`adjudication_performed` set to false. A semantic agreement is not a campaign
release-gate decision. The assignment and all accounted costs remain present.

An interruption or unknown operation raises sanitized `AttemptStopped`, retaining
the original checkpoints and usage. It does not fabricate a terminal failure or
authorize retry. Any non-settled/unknown row blocks continuation. Saved stage
proofs must reconstruct before subsequent work; missing operations, mismatched
receipts, changed grants, inconsistent totals or changed settings deny progress.
Checkpoint retries preserve original timestamps. Concurrent callers rely on the
existing ledger's unique operation reservation; a competing caller encountering
an active operation stops instead of issuing the same work again.

This coordinator's completed consumption requires the original live execution window
and current authority. It does not renew expired execution grants or roll clocks back.
The separate [completed semantic consumer](semantic-consumption.md) reconstructs
reviews after that window under fresh reporting permission; its original calibration,
qualification and data access must still be current. The
[whole-attempt report reader](completed-attempt-reporting.md) composes that evidence
with the unchanged original outcome, early failures and full account totals.

The owned composition tests use actual coordinator/stage APIs, model wire adapter,
receipt validation and SQLite accounting. Their qualification/calibration
authority, semantic context preparation and sandbox reports are controlled
fixtures. They test A/B agreement, retained failures, missing grants, immutable
checkpoint recovery, unknown operations, concurrent reservation refusal and
effect-free reconstruction. Injected post-commit exceptions establish recovery at
those boundaries, not actual process-crash or distributed-worker recovery. No
historical inputs, paid calls or campaign observations are exercised by this slice.

The separate [campaign journal](campaign-journal.md) now records registration, serial
intents, phase decisions and exact-case exposure across campaigns. Connecting that journal
to this executor and authoritative completed-result reporting remains required; journal
observations alone are not scoring, spending authority or numerical promotion evidence.
