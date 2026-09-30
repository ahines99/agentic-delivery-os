# PostgreSQL transaction and outbox fault matrix

`tests/test_postgres_faults.py` adds targeted persistence-boundary evidence to existing
concurrent-intake/budget and scoped-dispatch tests. It uses real PostgreSQL, with real
Temporal for start/redelivery cases. Faults are injected Python exceptions at specified
boundaries; these are **not process crashes, database restarts or network partitions**.
All data, actor, repository, workflow and queue identities are synthetic and unique.
No provider/model calls or global row deletion occur.

## Recorded local run

On 2026-09-28, all **12 cases passed in 6.11 seconds** against local PostgreSQL on port
25432 and Temporal on port 27233. The matrix covers:

| Boundary | Exercised behavior and required result |
| --- | --- |
| After each intake SQL insert: work item, workflow, command, inbox, outbox | An exception after the actual insert but before commit rolls back every inserted row. A retry plus duplicate delivery produces one logical workflow and one start outbox record. Six cases include the separate precommit case below. |
| Immediately before the database commit call | The hook observes every expected intake row inserted, then fails. Fresh-session reads find none of those rows committed. |
| Specification revision insert before commit | Failure preserves the previous workflow view and leaves no partial revision. Two subsequent identical recordings persist exactly one revision, without implicitly promoting it. |
| Intake response lost after successful commit | Repeating the idempotency key and redelivering the same source under another key both return the original logical workflow; one work item, workflow, start command and outbox remain. |
| Old lease acknowledged after a new owner reclaims it | The old owner's acknowledgement changes nothing; the current owner can mark the outbox delivered. |
| Temporal accepts start, response then appears lost | Retry resolves to the same actual Temporal run. |
| Temporal accepts start, outbox acknowledgement fails before its commit | The outbox stays pending; redelivery resolves to the same actual Temporal run. |
| Outbox delivery acknowledgement commits, then its response appears lost | Dispatcher error handling makes the row pending again; redelivery resolves to the same actual Temporal run. |

The initial specification is stored with the work item; intake does not create a separate
`specifications` row. The matrix explicitly checks that no revision rows survive failed
intake and separately faults a real revision insertion.

The three real Temporal redelivery receipts were:

| Simulated boundary | Workflow ID | Actual Temporal run ID |
| --- | --- | --- |
| Lost Temporal start response | `66dd0537-be1d-4b2c-a219-89233f0f3eda` | `01a0e896-318b-70fd-82b8-3b8ac681f50e` |
| Before outbox acknowledgement | `4e1797ba-95c8-43f4-814b-b0942872b42a` | `01a0e896-3801-7499-825a-0c694f7a2364` |
| After committed outbox acknowledgement | `7fd1a5cf-3af0-4aa4-a2ae-16a7d57b62af` | `01a0e896-3c80-70d4-84c0-e1bfbd6cdc9e` |

Each made two observed start requests and retained one distinct run ID. After redelivery,
a worker executed the production workflow/projector/command-resolution path with a
synthetic planner. An authorized canonical cancellation then reached `CANCELLED`; every
captured history replayed successfully. No candidate/model/publisher activity ran.

## Reproducing the scoped checks

```powershell
$env:TEST_TEMPORAL_ADDRESS = '127.0.0.1:27233'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://delivery:' + (Get-Content -LiteralPath '.local/postgres-password' -Raw).Trim() + '@127.0.0.1:25432/delivery'
.venv/Scripts/python.exe -m pytest tests/test_postgres_faults.py -q -s
```

The fixture skips explicitly when PostgreSQL is absent; Temporal cases additionally
require its configured address. It never silently substitutes SQLite for persistence
proof. SQLAlchemy fault listeners attach only to this fixture's database engine and are
removed in `finally` blocks. Reads and fault mutations are scoped to generated identities;
no other test/production rows are deleted. Receipts omit database URLs and credentials.

Lease expiration/backoff is accelerated by setting only the test's exact outbox row's
lease time to zero. This exercises reclamation and owner fencing without a minute-long
sleep; it is not a clock-skew experiment. The old-owner assertion concerns an already
**reclaimed** lease, not a claim that expiration alone invalidates all acknowledgements.

## Limits

The PostgreSQL server and Python process stay healthy; database-driver errors, disk loss,
failover, power loss, process kill and backup restoration need separate evidence. Raising
after a successful method return simulates caller uncertainty; no real response packet is
dropped. In the original run, the worker started only after redelivery, leaving the
execution open during duplicate starts. This result does not generalize to arbitrary
external side effects, exactly-once provider execution, or all terminal-workflow races.

Retained pending rows from pure persistence cases and closed workflows from Temporal cases
are synthetic test data, not campaign results. The fixture demonstrates these named M1/M4
boundaries; it does not close every transaction, recovery or operational release gate.

## Terminal redelivery follow-up (2026-09-30)

The same three acknowledgement boundaries now also execute to a terminal workflow
before the outbox is redelivered. An owned planner returns POLICY_BLOCKED through
the production workflow and projector. A subsequent duplicate start reaches the
actual Temporal server, which rejects reuse of that completed workflow ID. The
dispatcher acknowledges the retained outbox instead of creating another execution.

The test requires two observed start requests, one server rejection and the same
actual run ID. A fresh PostgreSQL engine confirms the unchanged terminal projection,
one workflow and one command. The complete decoded Temporal history remains equal
before/after redelivery and replays successfully. JSON object ordering is ignored;
all event data and event order remain part of the comparison. There is no model,
candidate or publication activity in the terminal case.

The combined suite passed **15 tests in 8.43 seconds** against a disposable database
and unique Temporal queues, including the original three active-redelivery cases.
Ruff, formatting and mypy passed. No production code change was needed: the existing
REJECT_DUPLICATE reuse policy supplies this behavior. This proves late start
redelivery for the named completed-workflow case, not remote side-effect recovery,
Temporal retention expiry or arbitrary terminal races.
