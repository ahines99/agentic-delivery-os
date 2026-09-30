# Read-only sealed candidate inspection

`validate_sealed_candidate` reconstructs a completed canonical A/B candidate from
existing protected source, frozen profiles, immutable checkpoints and settled
operation receipts. Its only asynchronous work is the pure candidate engine with
read-only callbacks. It has no model instance, credential lookup, runner, provider
call, artifact write, account allocation, reservation or checkpoint repair.

A separate finite `CandidateConsumptionAuthorization` pins the exact ledger target,
campaign/ordinal/phase, task and qualification, allocation/attempt/execution/result
references, and original execution/allocation policy and execution grant digests.
A trusted current consumption policy must allow the exact authorization digest and
purpose. `scoring` checks current qualification use for scoring; `campaign-report`
checks campaign use. Both require current qualification, calibration, data rights,
repository settings and disjoint stores before source reads and during reconstruction.
An expired qualification or data-use permission remains a refusal.

Original grant and policy documents are supplied as typed proof and compared with
the original digest bindings. They are never rewritten or stored retrospectively.
Completed operations must fall within their original grant windows and original
account-derived deadline. A fresh consumption grant may permit inspection after
that execution window expires; it cannot extend execution, mint spending capacity,
export a worker context or promote a phase. Existing allocator and executor contracts
and serialized artifacts are unchanged.

The reader rebuilds the same deterministic plan, full-source builder/reviewer
contexts, proposal edits, original regression checks, criterion checks and A/B
iteration decisions. It validates exact model forecast/output/configuration hashes,
provider/requested-model/rate-card/prices, distinct provider response IDs, original
reservations, measured infrastructure receipts, image/command/snapshot bindings,
collection and test phases, distinct nonces, and ordered ledger/checkpoint timestamps.
The reconstructed final candidate and engine evidence must match the recorded bytes.
Missing, unknown, extra or reordered candidate operations are refused. Candidate
rows and checkpoints are read again before return to detect changes during inspection.
Later settled account stages do not alter this candidate operation inventory.

The returned typed record contains references, status and operation IDs; it exposes
no source, model context, private oracle, stdout or reviewer prose. `strict_success`
remains false, including for `BUILD_VERIFIED` and `REVIEW_APPROVED`. A reconstructed
normal `FAILED` candidate remains failed and may contain retained candidate bytes.
The record is a validated snapshot, not a capability for a later action: downstream
execution still requires its own current authority and original finite account.

Owned tests use real SQLite and the production broker with controlled model/Docker
responses to produce evidence, then disable all mutation/model/runner boundaries
and remove credentials during inspection. They cover A, B repair, normal exhaustion,
expiry/revocation, alternate ledger targets and rehashed receipt/context/candidate
mutations. Qualification is an explicit controlled boundary in these fixtures;
these tests do not claim historical admission or model-quality measurement.

Storage administrators remain trusted: exact ledger-target identity is not a
cryptographic identity of database contents, and read-before/read-after comparisons
are not a transaction spanning all external authorization providers. No source is
exported by this API, and no historical scoring or campaign result is implied.


Version 2 of the consumption result includes [criterion execution counts](criterion-execution-evidence.md)
from its locally reconstructed final engine result. It cannot carry an earlier repair round's
passing tests to a different final snapshot. The original sealed candidate artifact is unchanged.
