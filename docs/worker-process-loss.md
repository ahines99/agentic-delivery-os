# Actual worker-process loss during candidate validation

The owned drill in
[`tests/test_worker_process_loss.py`](../tests/test_worker_process_loss.py) hard-kills
one disposable worker process while the production candidate pipeline is executing
a real Docker pytest validation. It uses actual PostgreSQL and Temporal, a unique
workflow/task queue, a frozen owned planner response and a controlled HTTP builder
response through the production model adapter. No external provider is called.

The parent verifies that the worker's ready PID equals the subprocess it created.
On Windows it launches the actual Python interpreter with the current environment's
site-packages, avoiding the extra process introduced by the virtual-environment
launcher. It observes a marker written inside the candidate test before killing
that exact worker process. The test workload sleeps for a finite sixty seconds;
the production runner's ninety-second command timeout is unchanged by the test.

The replacement worker uses the same unique queue. Production candidate activity
configuration has a twenty-second heartbeat timeout and one maximum attempt. The
drill checks an actual Temporal heartbeat-timeout event, exactly one candidate
schedule/start, durable `FAILED`, one unchanged settled builder operation, no review
or publication, and successful workflow-history replay. The generated test receipts,
builder usage, workflow projection, process/container identities and history remain
in the private test output. No historical inputs are used.

## Observed result and open defect

At production source `4ae9697`, the focused test passed in **25.84 seconds** using
`sha256:136340a9d0e974bb74700fd4caa874f4fefd757b6683e6347e83bf8228041138`.
After the worker was killed, the restarted worker returned durable `FAILED` in
**17.437 seconds** without repeating candidate work. The single scripted builder
call retained 3,000 microdollars of configured fixture accounting and zero reserve;
this is not a provider charge. There was no reviewer or paid model call.

**Automatic container cleanup did not occur.** The exact candidate container was
still running after the workflow failed. `DockerRunner.run` removes its container
in a Python `finally` block, which cannot execute after the worker process is
hard-killed. The current container's idle PID 1 also outlives the command timeout,
whose enforcement resides in the lost worker. Reaching terminal `FAILED` therefore
does not prove that its sandbox has stopped.

The parent test inspected that orphan before any cleanup, then explicitly removed
only the recorded container ID after rechecking its identity, name and managed
label. All three recorded containers (preflight, baseline and candidate) were absent
afterward. The disposable local database was removed separately by the private run
driver; no shared table, unrelated container or service was removed. This parent
cleanup is test hygiene, not automatic recovery evidence.

Private observation identities:

- Workflow/account: `dd346a21-917c-4861-a02e-305475aeb4ec`.
- Killed/replacement worker PIDs: `119344` / `48492`.
- Orphan explicitly removed: `9b5b86ea86fd87dd4fbb0a94ffd9701c1ebb237c5f510ca52c5813dcb5d0f826`.
- Temporal history SHA-256: `3a366e08ada46ebae584939dbc334ab2b37ce944381ff9caaa512930b9cc9161`.

Two earlier setup attempts were retained: a Windows path-length failure before any
worker started, and a launcher-PID mismatch before workflow dispatch. Neither was a
process-loss experiment; both disposable databases were removed. The successful
drill uses a shorter private artifact path and verifies the actual worker PID.

## Smallest next production scope

Add explicitly authorized, bounded reconciliation for the broker-owned container
identities after candidate heartbeat loss, while preserving the existing no-retry
candidate policy. Resource identities need durable recording around provisioning
so a replacement process can distinguish this run's resources from unrelated or
still-active work. Cleanup uncertainty must remain visible and must never create a
success/cancellation acknowledgement. A container-side finite lifetime would limit
continued work if the control-plane worker disappears, but does not alone prove
resource removal or replace reconciliation.

This is a proposed follow-up, not an implemented fix. The current test deliberately
records the open orphan condition; a future fix must replace that expectation with
proof of automatic bounded cleanup before the parent fallback runs. P-05 and the
broader daemon/host-loss and provider-uncertainty gates remain open.

To repeat against isolated test services, configure `TEST_DATABASE_URL`,
`TEST_TEMPORAL_ADDRESS` and immutable `TEST_SANDBOX_IMAGE`, then run:

```sh
uv run --no-sync python -m pytest tests/test_worker_process_loss.py -q
```

The test skips without actual PostgreSQL, Temporal and an image. Keep generated
configuration, logs and artifacts private; the worker bundle contains the supplied
database configuration. This is one bounded process-loss observation, not a general
recovery SLA, host-loss test, paid-provider reconciliation or release qualification.
