# Accounting metadata and preparation inventories

`read_accounting_snapshot(...)` reconstructs selected evaluation accounts from explicit
account/operation metadata columns. It never reads operation result payloads, checkpoints,
model responses, task text or reference artifacts. The trusted caller supplies an exact
ledger target identity, a finite distinct account list and a current authorization guard.
The guard runs before access, after reads and before the result returns. This low-level
reader does not mint report permission or independently authenticate its caller.

For every present account it validates status, chronology, immutable reservation bounds,
resource classification, summed account counters and original budget ceilings. Settled
model/infrastructure costs, unresolved reservations and settled/reserved tokens remain
separate. RESERVED and UNKNOWN operations retain their full reservation. A settled zero-cost
operation is distinct from an unresolved operation. Missing requested accounts are listed
explicitly and never materialized as fabricated zero-cost account records. Inconsistent
metadata makes the snapshot unavailable.

## Consistent read boundary

SQLite uses a read transaction with its connection's temporary `query_only` setting; the
original setting is restored before pool reuse. PostgreSQL uses a read-only repeatable-read
transaction. Both account and operation rows therefore come from one transaction snapshot.
These choices follow the documented [SQLite transaction behavior](https://www.sqlite.org/lang_transaction.html),
[SQLite query-only setting](https://www.sqlite.org/pragma.html#pragma_query_only) and
[PostgreSQL transaction modes](https://www.postgresql.org/docs/current/sql-set-transaction.html).
No reservation, settlement, checkpoint or account write occurs in either reader.

Snapshots include their observation time, selected identities, immutable metadata digests
and explicit counters. They describe the selected ledger at that observation; they neither
freeze later account activity nor establish provider invoice reconciliation. The trusted
database owner can alter records; these hashes are not an external cryptographic attestation.

## Pinned preparation inventories

`capture_preparation_inventory(...)` reads one account and writes a metadata-only artifact
binding its ledger identity, account creation time, budget digest, all observed operation IDs
and immutable reservation terms. It returns the `PreparationAccountIdentity` used by campaign
registration. The capture can retain unresolved operations without declaring them settled.

`reconcile_preparation_accounting(...)` reopens the exact pinned inventory and current account
metadata. Existing reservations may settle normally. Added/removed operations, changed
reservation terms, replaced accounts, changed budgets, mismatched ledger bindings and
missing accounts cause refusal. It does not silently generate a replacement inventory.
Program account IDs must be distinct across selected ledgers to prevent counting copied
accounts twice. Each ledger is read consistently; multiple ledgers do not share a distributed
transaction snapshot, and their individual observation times remain visible.

The reconciler writes neither artifacts nor ledgers and aggregates every selected account,
including failures and unresolved reservations. `selected_accounts_settled` only describes
the referenced accounts. Both inventory and report retain explicit false fields for full
campaign completeness: the controller still must establish that its registered inventory
covers the entire preparation program, link every campaign attempt and apply the frozen
cost limit. Arbitrarily selecting a cheap subset cannot prove that gate.

## Verification

Twenty-six focused tests passed with actual SQLite and PostgreSQL (2.10 seconds). They cover
mixed resources, missing accounts, unknown usage, zero-cost settlement, authorization denial,
counter/chronology corruption, exact inventory bindings, changed scope/terms and read-only
reconciliation. A concurrent settlement between account and operation reads preserves the old
consistent snapshot on both databases; a subsequent snapshot observes the new settlement.
SQL observation forbids payload-column reads, and class-wide write guards cover reconciliation.
The PostgreSQL test verifies its actual isolation/read-only modes, uses a unique disposable
database and verifies removal. These tests establish accounting metadata behavior, not a
historical scoring campaign, a complete invoice or phase promotion.
