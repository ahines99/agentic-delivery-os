# Active Docker cancellation drill

`tests/test_active_cancellation.py` exercises a running Docker workload through an actual
Temporal `DeliveryWorkflow` and the production `Activities.candidate` activity, with a
real PostgreSQL command ledger and state projection. It is a bounded M4 operational
fixture, not evidence that every cancellation, recovery or isolation gate is closed.

## Recorded local result

On 2026-09-28, the isolated drill passed against local Temporal at `127.0.0.1:27233`,
PostgreSQL at `127.0.0.1:25432`, and the existing sandbox image
`sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8`.

| Observation | Result |
| --- | --- |
| Workflow | `173c69a3-e33f-469e-acc4-6314e61a8044` |
| Command enqueue through durable cancellation and container absence | **15.359 seconds**, below the 30-second requirement |
| Durable state read through a fresh PostgreSQL store | `CANCELLED` |
| Canonical cancellation command disposition | `APPLIED` |
| Managed containers carrying this workflow's label after cancellation | `0` |
| Captured Temporal history replay | Passed |
| Paid model/provider calls and recorded model spend | `0` |
| Scoped test result | `1 passed in 20.85s` |

The test uses a synthetic immutable plan and replaces the paid `build_and_review`
boundary with a known long-running workload. The production candidate activity still
performs its approval/configuration checks, heartbeat, wall-time bound and cancellation;
`DockerRunner.run` still provisions, executes and removes the real container. The
production workflow, canonical command resolver, scoped dispatcher, command disposition
and state projector are exercised unchanged. This is not an end-to-end model/build trial.

### Cleanup-failure and approval-expiry follow-up

Three real-service drills passed together after the cleanup-error handling correction
(`3 passed in 43.52s`). Each replayed its Temporal history and left zero containers carrying
its own workflow label; no provider calls, model spend or PR publication occurred.

| Case | Workflow | Terminal state | Trigger through terminal state and container absence |
| --- | --- | --- | --- |
| Canonical authorized cancellation | `566a829f-76cd-4fc5-8762-520c0749c280` | `CANCELLED` | 15.359 seconds |
| Injected failed cleanup acknowledgement | `e72622e0-0156-4994-86a8-f436fcee26e5` | `FAILED` | 15.312 seconds |
| Approval expiry during execution, no cancel command | `c7799505-9ea6-444a-b556-8f82a22803b0` | `FAILED` | 4.265 seconds |

The negative cleanup test returns a failed acknowledgement only **after real Docker removal
succeeds**, so it does not create an orphan. It asserts the runner raised `SandboxError`
and requires `FAILED`, never successful `CANCELLED`, when cleanup is uncertain. Initial
workflow `70ea2f47-91bc-48d8-8737-ecc612240968` reproduced false `CANCELLED` despite that
exception. The corrected activity preserves cleanup exceptions, and the workflow's
`verified-cancellation-outcome-v1` patch distinguishes completed cancellation from other
activity failures. The follow-up passed with `FAILED`. This is controlled failure-handling
evidence, not an actual Docker daemon failure or proof of orphan recovery.

The expiry case ages only its disposable approval record after observing the workload and
child process. The production monitor retains its five-second interval. No cancellation
command is sent; the monitor detects expiry, terminates execution and records `FAILED`.
Changing that synthetic database timestamp is explicit fault injection, not an actual
operator revocation or a claim that wall time elapsed naturally. It tests this expired-
approval branch, not every live settings reload, authorization or clock-failure scenario.

## What the test establishes

The test creates unique workflow, ticket and queue identities and dispatches only that
workflow's outbox. It records a reviewer-authorized plan approval, waits for
`IMPLEMENTING`, then observes a marker written by the actual container workload after it
launches a child process. The parent repeatedly hashes data; the child remains running.
It inspects the container as running, nonroot, without a network or host bind mounts and
with a read-only root. A synthetic host environment canary must be absent inside the
container before the marker is written.

Only after active execution is observed does the test enqueue a canonical `cancel`
command with the current sequence/specification digest and an operator-authorized actor.
The signal goes through the scoped dispatcher and production resolver. The monotonic
timer starts before command enqueue and ends after workflow completion, workload cleanup
and absence of this workflow's labelled containers. The deadline is 30 seconds. The
production runner removes the container, ending its parent and child processes. A fresh
store verifies durable `CANCELLED`, the audit transition and zero spend; history replay
checks deterministic workflow behavior. No PR publication is reached.

Cleanup on a failed assertion may remove only exact container names observed by this
runner and returned under this run's UUID labels. It does not remove unrelated containers
or prune Docker volumes. A cleanup fallback does not turn a failed deadline into a pass.

## Repeating the drill

Configure an authorized disposable PostgreSQL database, local Temporal and an already
available pinned sandbox image. The test does not pull or build an image, obtain provider
credentials, or call a paid model. Existing tests use these same opt-in environment keys:

```powershell
$env:TEST_TEMPORAL_ADDRESS = '127.0.0.1:27233'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://delivery:' + (Get-Content -LiteralPath '.local/postgres-password' -Raw).Trim() + '@127.0.0.1:25432/delivery'
$env:TEST_SANDBOX_IMAGE = 'sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8'
.venv/Scripts/python.exe -m pytest tests/test_active_cancellation.py -q -s
```

The test skips explicitly when required service configuration is missing or when given
SQLite. It emits a small JSON receipt containing the workflow ID, elapsed cancellation
time, state, remaining-container count and image; it never prints database credentials or
the host canary. The actual local PostgreSQL and Temporal records retain the drill's
command/history evidence. Each repeat creates a new identity and must independently meet
the deadline; this one observation is not a percentile or reliability estimate.

## Remaining boundaries

The test invokes the internal authorized command ledger/dispatcher, not HTTP bearer-token
authentication, ingress TLS or a live operator UI. It demonstrates cooperative Temporal
activity cancellation delivered through heartbeats while Docker and the worker remain
healthy. It does not establish cleanup after host loss, daemon failure, network partition,
worker process kill, arbitrary hostile code escaping the container, or publication already
in flight. Those scenarios require separate drills and evidence. The observed timing
includes SDK heartbeat delivery; it is not a promise that cancellation is instantaneous.
