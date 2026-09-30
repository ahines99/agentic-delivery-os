# Reconcile registered program capacity with actual ledgers

`reconcile_program_accounting(context=...)` reads a concrete
[program registry](program-budget.md) and exactly its bound ledger targets. The caller
supplies actual `EvaluationExecutionStore` instances and a current full-scope metadata guard.
That guard receives the sorted complete target list before any ledger read. The registry's
own current permission remains required. Missing, extra or mismatched targets are refused;
the reader never creates a missing database, enrolls a target, or repairs a partial account.

For each target, one read-only transaction captures the registry/target binding, every
account and operation's allowed accounting columns, and local OPEN/CLOSED markers. SQLite
uses the existing query-only transaction boundary; PostgreSQL uses read-only repeatable read.
The shared metadata reader retains its selected-read and whole-ledger limits, orphan checks,
chronology checks and counter reconstruction. Program totals are additionally bounded to
10,000 accounts and 100,000 operations across the entire supplied collection; excess is
refused, not truncated. No operation result, checkpoint payload, source, task text, reference
answer, or model output is loaded.

Each local binding must match the registry identity and enrolled target nonce. Local account
state rows must correspond one-to-one with actual accounts. Actual budgets must match the
registry's immutable budget digest; observed settled cost plus reservations must fit its
envelope. Every actual account must have an envelope, including zero-cost accounts.

| Registry envelope | Local account | Reported condition |
| --- | --- | --- |
| HELD | Absent | PENDING_CREATION; observed usage is null and the full envelope remains held |
| HELD | OPEN, no operations or usage | PENDING_ACTIVATION; no activation is performed |
| ACTIVE | OPEN | ACTIVE; actual settled/reserved usage is retained |
| ACTIVE | CLOSED, fully settled | CLOSURE_PENDING; concrete settled cost is visible but the registry still holds its full maximum |
| CLOSED | CLOSED, fully settled | CLOSED only when local receipt totals, local closure amount and registry closure amount agree |

An absent ACTIVE/CLOSED account, unexpected account, invalid binding, changed budget,
unresolved closed account or inconsistent closure amount makes the report unavailable.
An incomplete but valid setup state is preserved explicitly; it is not converted to a
zero-cost successful attempt. All-closed is false for an empty program.

## Consistency, permission and reporting

The reader reconstructs every ledger twice and requires unchanged accounting and local
state, excluding only observation timestamps. It rereads the registry and requires the
same complete registry snapshot. Guards are rechecked during and after reads. Each ledger
transaction is consistent; this is not a distributed atomic snapshot or a guarantee that
no state can change after return. A changing settlement, new envelope, closure, binding or
scope cannot be silently blended into one successful reconstruction.

`observed_totals` describe concrete ledger usage. Registry `held_microdollars` describe full
maximum liability for HELD/ACTIVE envelopes; `closed_microdollars` describe concretely
closed spend. These views overlap: never sum them as independent charges. Pending creation
has null per-account observed usage, with its full liability still visible in the registry.
Approved but not yet enrolled targets remain visible through the registry policy and
`all_approved_targets_enrolled=false`.

The [campaign report](campaign-reporting.md) optionally accepts a `ProgramAccountingContext`.
Its execution ledger must be the same actual store instance in that program context.
The report requires separate full-scope and registry permission, rereads the program result
after normal attempt/preparation reconstruction, and compares it again. No context means
NOT_REQUESTED. Inconsistent evidence means UNAVAILABLE; revoked scope/registry permission
denies the requested report. OBSERVED includes valid partial states and does not mean the
program or campaign is finished. The existing selected accounting totals remain separate.

With a [schema-2 registry](program-legacy-liabilities.md), the context must also supply the
exact concrete legacy collection and current permission. Reconciliation matches its archived
binding, accounting and liability to the original pinned inventory before and after reading
prospective ledgers. Schema-2 reports expose `legacy_settled_microdollars` and
`legacy_reserved_microdollars` separately; existing `observed_totals` remain prospective.
`historical_costs_included` is true only for that declared, reconstructed archived selection.
Missing legacy context or changed archive facts refuse the current report.

This does not attest that all historical ledgers were declared, reconcile external invoices,
or authorize spending/promotion. `complete_program_cost`, `distributed_atomic_snapshot`, `model_results_read`,
`ledger_mutations` and `execution_authorized` remain false. Closing all current program
envelopes cannot mark unrun campaign assignments complete or repair a missing preparation
inventory. Program-wide release accounting remains open until the other scope obligations
are concretely established.

## Verification scope

Owned SQLite tests cover full ledger totals, retained unknown reservations, every supported
partial boundary, read-only handles, missing/extra accounts and ledgers, changed budgets,
closure/binding/state inconsistencies, concurrent settlement, and current scope denial.
SQL observation forbids model-result/checkpoint reads, class-wide guards forbid accounting
mutations, and database bytes remain unchanged during the read-only path.

The PostgreSQL fixture checks actual read-only repeatable-read modes for both passes,
matches registered closed cost to real ledger accounting and verifies temporary database
removal. Aggregate tests use real registry/journal/accounting records, with explicitly owned
campaign qualification fixtures. They preserve missing preparation inventory, deny changed
or revoked program scope, and retain all unrun assignments. No live historical ledger,
private answer, paid request or phase promotion is involved.

The combined program accounting, registry, accounting inspection, ledger coverage and campaign
reporting scope passed 84 tests in 140.21 seconds with actual PostgreSQL and no skips. After
adding registry-only concurrent hold changes, registry permission revocation and approved but
unenrolled target cases, the final focused scope passed 23 tests (17 deselected) in 13.86
seconds. These overlapping scopes are not additive. Production source was unchanged between
the runs. Ruff/format (368 files), mypy (116 sources), and source/wheel builds passed.
Exact-head hosted CI and independent review remain outstanding.
