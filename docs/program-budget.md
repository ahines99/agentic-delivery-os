# Prospective shared evaluation budget

[ADR-020](adr/ADR-020-prospective-program-budget-envelopes.md) adds a shared accounting
boundary below preparation, calibration and campaign account creation. It is opt-in for
new evaluation ledgers. The registry itself authorizes no model, repository or runtime use.

The trusted controller constructs an immutable `ProgramBudgetPolicy` with its approved
program identity, accounting authorization reference, finite cap and exact ledger targets.
`configured_ledger_identity(url)` derives a target pin without opening/creating the database;
it has the same password-independent identity rules as the existing ledger reader.
`ProgramBudgetRegistry.create(path, policy, current_guard=...)` exclusively creates a new
registry; the filename must match `delivery_eval_program_*.sqlite` or `.db`. Reopening uses
`ProgramBudgetRegistry(path, current_guard=...)`. The guard must validate current program
accounting permission; it is not a substitute for existing execution/data/model grants.
The guard must not reenter enrolled-ledger transactions. Registry and ledger files belong
outside worker-visible mounts and remain writable only by trusted controllers/operators.

Create each empty target with `EvaluationExecutionStore(url, program_budget=registry)`.
It enrolls only a policy-approved target and writes its schema-2 binding. Existing schema-1
ledgers are refused for enrollment, without changing their original budgets or evidence.
Every existing caller of `create_account`, `reserve` or `reserve_infrastructure` on this
bound store receives the shared enforcement. No separate opt-in is needed per operation.
Opening the same store without its registry cannot bypass new-spending checks.

## Capacity and account lifecycle

The shared cap includes full account envelopes before any operation reservation, including
preparation/calibration accounts and both model/infrastructure limits. The registry retains
canonical budget metadata and rederives each ceiling during every registry transaction;
a changed ceiling cannot silently manufacture additional capacity. This is conservative
capacity, not billed spend. A HELD or ACTIVE envelope consumes its full maximum even when
the account has partially settled work. An unresolved operation retains that envelope.

After the final stage (including any intended adjudication), the controller can call
`store.close_program_account(account_id)`. It does not expire or renew any grant. Closure
blocks new local reservations first, then reduces the global envelope to concretely verified
settled cost. It is irreversible. Original immutable settled results remain readable, but
new model/infrastructure operation IDs are refused. Account IDs cannot move across targets
or be recreated after loss of an ACTIVE local account.

Partial account creation and closure retain capacity. Retry the same identity to reconcile
only the supported partial state; do not create a replacement account to bypass uncertainty.
The registry never deletes unknown liabilities or accepts a reported zero as proof of closure.
Actual provider invoice reconciliation and distributed worker quiescence remain separate.

`registry.snapshot()` reports the immutable policy, bound targets, all account envelopes,
held maxima, concretely closed spend and remaining capacity. Those values must not be added
to ledger spent/reserved totals: they describe overlapping views of the same accounts.
Snapshots are transactionally consistent registry metadata, not a distributed census of all
ledgers. The [concrete reconciliation reader](program-accounting.md) now checks every bound
ledger against those envelopes, preserving partial boundaries and actual observed usage. `historical_costs_included`, `complete_program_cost` and `execution_authorized`
remain false. Existing [preparation inventories](campaign-accounting.md) are not silently
imported or dropped; incorporating their retained liabilities is unfinished release work.

## Verification

Owned tests exercise actual SQLite ledgers/registries and a disposable real PostgreSQL
ledger. They cover concurrent cross-ledger admission, full retained uncertainty, local
insert/activation/closure failures, exact recovery, forged or open closure requests,
reopening without authority, revocation, lost ACTIVE accounts, corrupted counters, schema
and identity drift, infrastructure accounting, and closure/reservation races. PostgreSQL
database cleanup verifies absence. Existing legacy accounting tests remain applicable.

Concrete campaign allocator checks exercise sufficient and insufficient registry capacity
for both protocol versions, retaining the fixtures' explicit qualification/runtime boundary.
No historical payload, live registry enrollment, paid call or release promotion is implied.


The initial registry/legacy-store scope passed 64 tests with one unconfigured PostgreSQL skip
in 5.44 seconds. The expanded registry/store/snapshot/allocation scope passed 123 tests with
one unconfigured dedicated allocation-database skip in 14.07 seconds. After adding concrete
v1/v2 allocator admission cases and provisioning that separate owned database, that
scope passed all 128 tests in 14.43 seconds with actual PostgreSQL and no skips. Every temporary
database was dropped and its absence checked. These scopes overlap and are not summed.

The final canonical-budget hardening and additional smaller/larger ceiling, policy and
schema tampering cases passed the expanded 131-test scope in 15.84 seconds, again with
actual PostgreSQL and no skips. The registry now recomputes envelope ceilings from retained
budget terms on every transaction instead of trusting a separately stored ceiling alone.
Ruff/format (365 files), mypy (115 sources), package builds and 494 local documentation links
passed. These checks do not replace new-head full CI or independent review.
