# Completed deterministic scoring inspection

`validate_completed_scoring_consumption` is a separate, effect-free reader for the
existing schema-2 deterministic campaign scorer and schema-3 frozen campaign. Existing
live execution APIs and `validate_completed_scoring` keep their original deadline
checks and serialized contracts. This reader neither renews them nor rewrites clocks.

A fresh `ScoringConsumptionAuthorization` pins the exact ledger target, existing
account/campaign/ordinal/phase, attempt and scoring-binding references, candidate
artifact/digest, task/qualification, original scoring grant/policy digests and original
completed-evidence digest. Trusted current policy must permit that exact authorization
digest and purpose. The finite inspection window is at most 24 hours and creates no
spending budget, allocation, model invocation, worker export or phase transition.

Both `deterministic-scoring` and `campaign-report` consumption require current
qualification **scoring** use: reconstructing a score reads protected source and
oracle tests, and its original binding hashes the admitted scoring-use record.
Current qualification, calibration, data rights, repository settings, preparation
policy and disjoint artifact/ledger scope remain required before and through reads.
Expired or revoked qualification is not replaced with historical execution authority.

Original execution grant/policy documents are supplied as typed immutable proof and
checked against their exact original bindings. All operations must have occurred
within the original scoring grant and attempt deadline. Inspection may occur after
that deadline only under fresh current consumption authority. No caller-supplied fake
execution object, clock rollback or renewed execution grant is used.

The reader reconstructs frozen campaign schedule/caps, unchanged attempt budget,
source/candidate/oracle preservation, commands and exact scoring-binding metadata.
It requires exactly the three scoring operation IDs (preflight, acceptance,
regression), known settled receipts, exact original infrastructure rates/reservations,
zero model-token usage, measured cost and ordered aware checkpoint/operation times.
Both collector reports must bind exact image/command/snapshot and distinct 32-character hexadecimal
nonces, collect every frozen node and retain complete valid setup/call/teardown
phases. Complete assertion failures remain valid failed evidence; collection errors,
missing phases, timeout or malformed output are refused.

The current harness retained only an empty successful preflight result, not the
probe checks. The reader verifies that exact completion/accounting marker; it does
not invent unavailable detailed preflight evidence. All three receipt digests and
both command artifact references must reconstruct the original completed-evidence
digest. Rows/checkpoints are re-read before return to detect concurrent changes.
Later settled account stages are not interpreted as additional deterministic scoring.
This API makes no claim to reconcile unrelated account operations or their unknowns.

The typed result contains references, deterministic booleans, receipt digests and
these three operations' infrastructure cost. No source, oracle, logs, node names or
model judgment is returned. `strict_success` remains false even when both suites
passed. It is not semantic scoring, candidate-origin validation or a campaign result.
Existing noncanonical schema-2 attempt accounts remain inspectable when explicitly
pinned; inspection does not infer a canonical allocation or authorize another account.

Production wiring still needed: a trusted coordinator must validate the candidate
handoff, issue/pin this exact read-only grant, and use this API when an execution
window has expired. It must separately validate semantic results and complete account
accounting before constructing campaign outcomes. Existing semantic context/execution
paths continue using their live readers; this addition does not silently change their
authority or resume behavior. Semantic completed-history inspection remains separate.

Owned tests produce evidence with real SQLite and controlled qualification/Docker
responses. They disable artifact writes, ledger mutations, broker credentials/models
and runner construction during reads; compare account/operation/checkpoint snapshots;
and test expiry, revocation, alternate targets/scopes, unknown/missing/extra operations
and fully rebound report/rate/reservation/timestamp mutations. They do not claim
historical admission, actual Docker execution in this suite or semantic correctness.
Same-target database replacement by an administrator remains outside the ledger-target
identity guarantee. Read-before/read-after checks are not a transaction across all
external authorization providers. No paid call or historical payload read was used.
