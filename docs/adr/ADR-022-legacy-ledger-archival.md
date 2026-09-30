# ADR-022: Archive legacy ledgers before incorporating historical liability

Status: implemented with scoped SQLite/PostgreSQL verification; registry incorporation and
live historical archival remain unfinished.

## Context

[ADR-020](ADR-020-prospective-program-budget-envelopes.md) reserves prospective capacity,
and [ADR-021](ADR-021-required-evaluation-program-enrollment.md) requires enrollment at
execution entry points. Existing schema-1 ledgers have spending and unresolved reservations
that are not covered by those envelopes. A point-in-time metadata inventory cannot safely
be treated as fixed historical liability while writers can add accounts or operations.

## Decision

Add an explicit irreversible legacy archive transition, separate from prospective enrollment.
The trusted operator must stop older writer processes and active workloads before invoking
it under current permission for the exact ledger. No automatic migration runs at startup.
The transition validates the complete accounting metadata, retains original tables and rows,
adds an authorization/target/nonce/time binding, and changes the schema marker to version 3.
Schema 2 remains the distinct prospectively enrolled ledger format.

All current store mutations acquire the ledger marker lock before account/operation locks.
The same lock serializes archival with PostgreSQL writers; SQLite uses its existing immediate
transaction. Handles opened before archival reread the marker before every mutation. Archived
ledgers refuse account creation, model/infrastructure reservation and settlement, observations
and checkpoints. Existing account, receipt, checkpoint and metadata inspection remains possible.
Completed-evidence inspection cannot acquire new spending capacity.

The metadata-only archive reader validates the concrete archive binding and entire ledger in
one read-only snapshot. Its conservative liability is settled model/infrastructure cost plus
all unresolved model/infrastructure reservations. It never reads operation result payloads or
turns an unknown charge into zero. Account and operation timestamps must precede archival.
The returned stable accounting digest excludes only observation time. A parsed report is not
authority; a later registry integration must consume concrete archived stores and retain their
bindings, accounting digests and liabilities.

## Recovery and limits

Failure before commit rolls back both metadata and schema changes. A read or permission failure
after commit leaves the safe archive fence in place. Repeating the same authorized transition
returns the same archive binding; a different authorization cannot rewrite the original one.
No reopen, reservation release, replacement account, or migration to execution authority exists.

Archival also stops late settlement through this store. Reconcile available provider usage
before archiving; unresolved reservations remain conservative liability. A future separately
designed provider-evidence adjustment must not rewrite original archived records. This change
does not implement that adjustment, registry incorporation, a complete program inventory,
invoice reconciliation, distributed workload quiescence, or new execution authorization.

Database owners and trusted controllers remain trusted. Current code cannot fence an already
running older binary that never checks the marker, or an administrator using direct SQL.
Stopping those writers is a prerequisite, not a capability inferred from an archived row.
No live historical ledger has been archived by this implementation work.
