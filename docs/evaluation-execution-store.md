# Separate evaluation usage ledger

`evaluation.execution_store.EvaluationExecutionStore` provides durable model-usage
accounting for a trusted evaluation controller. It has an independent SQLAlchemy schema
and database, with no fake delivery workflows and no changes to delivery tables or
migrations. Account creation is **not authorization to run tasks or spend money**.

## API and database ownership

```python
from agentic_delivery.config import Budget
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore

ledger = EvaluationExecutionStore("sqlite+pysqlite:///delivery_eval_local.db")
ledger.create_account("qualification-run-1", Budget())
cached = ledger.reserve("qualification-run-1", "qualification-run-1:qualifier-a", 1000, 200, 100)
```

The example performs bookkeeping only. Issuing a provider call remains the controller's
separately authorized decision. Always close the engine with `ledger.engine.dispose()`
when its owner finishes.

SQLite requires an existing parent directory and a filename matching
`delivery_eval_<name>.db` or `.sqlite`. In-memory and URI-query aliases are refused.
PostgreSQL requires a separately provisioned database named `delivery_eval_<name>` and
the public schema. The constructor does not create or drop PostgreSQL databases.
It rejects foreign tables/views and unknown/incomplete ledger schemas before initializing
its own four tables: `evaluation_ledger`, `evaluation_accounts`, `evaluation_operations`,
and `evaluation_checkpoints`. The schema-version marker is `evaluation-only` / `1`.
It never invokes the delivery migration system or shared `Base.metadata`.
Reopening inspects exact column names, dialect types, nullability/defaults, primary-key
columns and foreign-key targets/options before any mutation. A correct version marker
does not excuse schema drift; missing, renamed or extra columns and altered constraints
are rejected. Schema migration is not implicit repair.

- `create_account(account_id, budget)` creates an account or returns the identical
  existing account. Budget changes are conflicts. Use a new explicitly authorized account
  for a different allocation; creating another account does not override a campaign cap.
- `account(account_id)` returns current budget totals and creation metadata.
- `reserve(account_id, operation_id, cost, input_tokens, output_tokens)` atomically
  reserves worst-case usage and returns `None`, or returns an already-settled cached result
  for the same account, operation and reservation. IDs are globally unique within this
  dedicated ledger. Cross-account reuse and changed reservation values are rejected.
- `settle(operation_id, *, cost, input_tokens, output_tokens, result)` records actual
  nonnegative usage no greater than the reserved bounds. Identical repeated settlement is
  idempotent; differing cost, either token count or result is a conflict. Results must be
  finite JSON objects within 1 MiB. Actual zero usage is distinct from an unknown outcome.
- `operation_receipt(account_id, operation_id)` returns scoped account/operation identity,
  reserved and actual cost/token counts, status, result, timestamps, schema version and
  a SHA-256 `receipt_digest`. Reads return detached data; mutating returned dictionaries
  does not mutate storage. The trusted model broker additionally validates request and
  provider provenance stored inside `result["operation_receipt"]`; a ledger digest alone
  is not provider authentication or a reason to trust a changed request's cached answer.
- `record_observation(account_id, operation_id, observation)` records the first immutable
  bounded finite JSON observation on an unresolved reservation. The same value is
  idempotent; changed observations, cross-account access, or adding an observation after
  settlement are rejected. An exact already-recorded observation remains idempotent after
  settlement. This method changes no budget, status or actual-usage fields.
  It stores the observation at `result["provider_observation"]` using the existing schema;
  receipt reads also expose an `observation` alias. Settlement preserves and merges that
  value, rejects caller attempts to replace it, and remains idempotent when the caller
  resubmits the same result without the observation field. Existing settled results with
  no observation stay unchanged. No migration, live-probe database alteration, retry or
  reservation release is implied. Fixed diagnostic field validation and redaction belong
  to the trusted provider broker; this ledger accepts JSON and is not a safe raw-response
  logging interface. Never pass credentials, prompt bodies or uncontrolled provider text.
- `checkpoint(account_id, stage, artifact_digest)` seals an immutable stage-to-artifact
  reference. Repeating the same reference returns the original checkpoint; replacing it
  is rejected. `checkpoint_receipt(account_id, stage)` returns that reference, or `None`
  when the existing account has not completed the stage. The controller must separately
  verify artifact bytes and semantic completion; a digest pointer is not a task verdict.

Identity strings are bounded, restricted ASCII identifiers. Accounts and operation/stage
names should bind campaign/task/configuration identities under controller policy. There is
no arbitrary SQL, execution, provider, deletion, reset, reservation-release or database-drop
API. The local database operator is trusted; raw SQL tampering is outside this ledger's
integrity boundary. Protect the dedicated database because model results can be sensitive.

## Conservative accounting and concurrency

`RESERVED` means outcome **UNKNOWN**, including a call that might have failed before any
provider spend. A repeated reservation is blocked until evidence supports settlement.
All reserved cost and tokens remain charged against the account. Failed/missing responses,
timeouts, cancellation and over-reservation provider reports cannot silently free budget
or trigger a second call through this store. A controller can settle a known result using
the same operation ID; unsupported uncertainty requires separate reconciliation policy.
Diagnostic observations do not establish successful output or known billing. A reserved
result containing only `provider_observation` is never returned as a cached success.

PostgreSQL locks the account row before operation mutation. SQLite enables and verifies
`PRAGMA foreign_keys=ON` for each new or checked-out connection, including reused pooled
connections, and uses `BEGIN IMMEDIATE`
to serialize writers. Reservation/account updates and operation inserts share a transaction;
settlement updates share a transaction and the same account-before-operation lock order.
Global operation uniqueness rolls back a competing account reservation on identity races.
Budget comparisons cover spent plus reserved microdollars, and actual plus reserved input
and output tokens. Integer values are strict and bounded to signed 64-bit storage.

`Budget` also contains wall/command-time and repair settings. They are retained as immutable
account metadata, but this ledger enforces **model cost and token totals only**. The execution
controller must enforce time, infrastructure cost, retry rules and campaign-wide allocation.
There is no hierarchy aggregating several accounts into a total campaign budget yet.

## Validation evidence and boundaries

The scoped test suite exercises unknown retention, immutable settlement and checkpoints,
cross-account denial, copied-result isolation, account ownership checks, strict numeric/JSON
validation, reopening, SQLite rollback faults and simultaneous budget admission.
It also rejects column/primary-key/foreign-key drift without repairing or writing to the
altered schema. Foreign-key enforcement is tested after pool reuse and new connections.
A controlled `StructuredModel` MockTransport call settles a real ledger entry, validates
its provider-operation receipt, reopens the SQLite ledger and reuses the exact cache
without a second request. Changed context is rejected. The fixture includes Unicode
output and checks the receipt's canonical JSON digest. This is synthetic transport
compatibility evidence, never a real provider call or billing observation.
Observation tests cover first-write immutability, account scope, unknown-budget retention,
rollback on write faults, preservation during settlement and unchanged-schema reopening.

The real PostgreSQL test creates a UUID-named `delivery_eval_` database after checking it
does not exist and differs from the configured delivery database. In that dedicated
database, eight competing reservations respect each cost/input/output cap; competing
accounts cannot both claim one operation; eight identical settlements charge once. The
first of eight conflicting observations wins without releasing the reservation, and its
value survives settlement. The
test also reopens and validates the PostgreSQL schema, then confirms an injected extra
column prevents reopening. It disposes all ledger connections and drops **only its verified created database** in
cleanup. It neither creates nor drops delivery tables. PostgreSQL coverage requires
`TEST_DATABASE_URL` with database-creation privileges; absence is an explicit integration
skip, not SQLite proof of PostgreSQL behavior. Test outputs never print credentials.

No historical task, model/provider call or evaluation campaign ran as part of these tests.
The ledger is groundwork for metered qualification and execution, not proof that a task
was qualified, a checkpoint is correct or a campaign's budget has been authorized.
