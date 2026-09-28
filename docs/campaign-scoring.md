# Versioned campaign scoring consumer

`score_campaign_candidate` explicitly consumes schema-3 execution campaigns with a
schema-2 `CampaignScoringAuthorization`. The legacy `score_candidate` route and its
schema-1 authorization keep their existing task-budget semantics.

The trusted controller must already have created one attempt account with the exact
frozen arm limits and recorded `campaign-attempt-v1`, pointing to an immutable
`CampaignAttemptBinding`. That record binds the campaign, ordinal, arm, original
qualified task manifest, qualification receipt, start and original deadline. Current
policy separately pins that attempt and campaign, permits its phase and caps every
arm limit. A candidate-specific finite authorization also binds current execution
and preparation policy. Parsing or freezing any of these documents grants no authority.

The scorer creates no account and cannot expand capacity. Builder, review and scoring
costs remain in the same existing account. An unresolved reservation denies scoring;
settled prior usage reduces remaining capacity. Preflight, acceptance and regression
reserve finite infrastructure costs and retain uncertain reservations on failure.
Exact settled stages can be reused. A changed candidate or grant cannot replace the
immutable scoring checkpoint. Current authority, policy, configuration and the
original attempt deadline are checked before and during effects. The command timeout
comes from the frozen execution arm; qualified task bytes and qualification limits
remain unchanged.

`validate_completed_scoring` reconstructs evidence without account, checkpoint,
reservation or Docker writes. It revalidates current authority, both checkpoints,
three settled operation receipts, candidate/test snapshot bindings, exact frozen
collections and complete setup/call/teardown reports. Receipt bindings require the
exact approved keys and distinct 32-hex suite nonces. Aware account/checkpoint/stage
timestamps must preserve attempt and authorization bounds, stage order, the current
time and original deadline. These are consistency checks on trusted stored evidence,
not authentication against arbitrary database writers. Complete ordinary test failures
produce a negative deterministic result; malformed or missing evidence denies
inspection. Its digest binds the exact account, attempt, candidate, authorization and
receipt references. Returned metadata excludes stdout and stderr. Deterministic
passing results do not establish independent semantic correctness.

Owned tests exercise the real SQLite ledger and production harness with explicit
qualification and Docker-result substitutions. They prove shared capacity, arm timeout,
immutable task bytes, current revocation/expiry, strict bindings, unknown-operation
refusal and read-only reconstruction within those boundaries. They do not establish a
qualified corpus, live Docker campaign, model spend or historical scoring result.

The campaign controller, aggregate spending/ordinal uniqueness, phase promotion and
semantic-scoring calibration remain separate work. This consumer neither creates
historical execution grants nor starts a campaign. A trusted controller must prevent
multiple account allocations for one ordinal and enforce the overall campaign cap.

The completed reader currently requires no outstanding reservation. A later semantic
executor using the same account must add an explicit trusted active-operation binding
before polling this reader during a model call. It must validate that operation's
ownership and immutable terms while continuing to reject every unrelated unknown
reservation; the current reader intentionally does not silently permit model spend.
