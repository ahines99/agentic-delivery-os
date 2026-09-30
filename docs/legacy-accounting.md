# Legacy ledger archival and liability

[ADR-022](adr/ADR-022-legacy-ledger-archival.md) defines the irreversible transition from
a legacy evaluation ledger to retained accounting evidence. It is separate from execution
enrollment and requires current permission for the exact target, plus stopped older writers
and workloads. Never run it automatically on startup or against a live campaign.

`archive_legacy_ledger(store, expected_ledger_identity=..., authorization_digest=...,
current_guard=...)` validates all accounting metadata before changing the schema. It preserves
original account budgets, operations, result payloads and checkpoints. The new archive binding
records target identity, authorization digest, nonce and time; the schema marker becomes 3.
Current handles, including those opened before archival, refuse all further store mutations.
Repeated calls with the same authorization return the original binding.

`read_archived_ledger_accounting(...)` reads the concrete archive binding and complete account
and operation metadata under current read permission. It returns settled costs, unresolved
reservations, their conservative liability sum, and a stable metadata digest. It contains no
model result payloads. Missing/corrupt state, changed target, invalid chronology or revoked
permission fails closed. Existing completed-evidence readers remain separate from this census.

Settlement after archival is refused too. Unknown operations retain their original reservation;
archival does not prove a workload stopped or that the provider billed nothing. Original records
are never rewritten to release liability. A lost response after archive commit is recovered by
reading or repeating the same transition, not by reopening the ledger.

The [schema-2 registry policy](program-legacy-liabilities.md) incorporates a concrete archived
selection into a new program cap. Full program inventory, live import, invoice reconciliation
and any later supported cost adjustments remain unfinished. This code has only been exercised with owned SQLite and
temporary PostgreSQL test data; historical ledgers and grants remain untouched.

## Verification

The final archive/store/registry/accounting scope passed 149 tests in 23.20 seconds with
actual PostgreSQL and no skips. It covers record preservation, uncertainty, pre-existing and
reopened handles, all mutation classes, reservation and settlement races, pre-commit rollback,
post-commit permission loss and same-identity recovery, schema/binding/chronology corruption,
and payload-free reads. Unique owned PostgreSQL databases were removed and absence verified.
An earlier run had 100 passes, 16 service skips and one test-call error (a missing account ID
in the observation fixture); after correcting the call, the then-current service-enabled
scope passed 135 tests. The final expanded scope above supersedes that narrower verification.
These overlapping counts are not summed. Full verification at the new source revision remains
required, as do registry incorporation and live archival prerequisites.
