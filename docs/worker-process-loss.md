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

## Original observation, retained before the fix

At production source `4ae9697`, the focused test passed in **25.84 seconds** using
`sha256:136340a9d0e974bb74700fd4caa874f4fefd757b6683e6347e83bf8228041138`.
After the worker was killed, the restarted worker returned durable `FAILED` in
**17.437 seconds** without repeating candidate work. The single scripted builder
call retained 3,000 microdollars of configured fixture accounting and zero reserve;
this is not a provider charge. There was no reviewer or paid model call.

**Automatic container cleanup did not occur at that revision.** The exact candidate container was
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

## Bounded cleanup follow-up

[ADR-015](adr/ADR-015-bounded-candidate-cleanup.md) adds a separately scheduled trusted
cleanup activity on candidate activity failure, behind a Temporal replay patch. The
candidate is never retried. Cleanup lists only exact workflow-scoped managed labels,
checks each full container identity and owned name before removal, then verifies
individual absence and an empty scoped listing. Preflight now shares the workflow
label with baseline/candidate execution. The cleanup activity grants no build,
publication, model or merge capability and does not require still-valid plan approval.

The implementation bounds cleanup to twenty seconds, sixteen listed containers and
five seconds per Docker command; the activity has a thirty-second total scheduling
deadline and one attempt. Confirmed absence produces an immutable `CLEANED` receipt;
cleanup failure, timeout or malformed result persists `UNKNOWN` with
`verified_absent=false`. The workflow remains `FAILED` in either case. It does not
turn resource cleanup into a successful delivery result.

The revised two-case drill passed in **51.46 seconds** on the same image. The normal
case reached failure after **18.250 seconds**, with automatic removal verified before
the parent fallback, which removed nothing. The second actual hard-kill case injected
a failure into the cleanup activity before removal; it reached failure after
**17.250 seconds**, persisted `UNKNOWN`, and left the orphan for exact-ID parent
cleanup. Both retained a single candidate schedule, a single settled builder call,
zero reserve, no reviewer/publication and successful replay. Both original and revised
observations remain retained; an injected cleanup failure is not a daemon-outage claim.
The retained pre-fix failure history (`3a366e08...9161` above), which reaches candidate
`ActivityError` without the new patch marker, also replayed successfully against the
new workflow code in a separate offline check. Existing active cancellation, cleanup
acknowledgement failure and approval-expiry drills passed again: three cases in
43.56 seconds. The focused cleanup/authorization/saved-replay suite passed 39 tests.

| Case | Workflow/account | History SHA-256 |
| --- | --- | --- |
| Automatic cleanup | `2ac266bc-acce-4b15-9a42-2fae4b02cea2` | `9adcb9187a19c233d9293b2a713b922e1f17d3affeedfaafdc4ce3049fbc2f35` |
| Cleanup uncertainty | `2c0c6d8f-43c4-417d-ae91-378e7b9a9aff` | `678d2eb44ff2eef602ce62e0a82cc28193a8fdf7106a827413289f321d44431a` |

**Absence is a point-in-time observation on the configured Docker host.** A heartbeat
timeout can also reflect a partition while a worker remains alive. Existing approval
and configuration checks do not provide a durable per-run cleanup lease that fences
such a worker from creating a later container. This change therefore proves the
killed-process case, not distributed fencing, host/daemon-loss recovery, all
provisioning races or a universal cleanup SLA. P-05 remains partial. The existing
two-hour keepalive exceeds the approved command deadline; a container-side lifetime
tied to the authorized deadline and durable resource/lease reconciliation remain
separate work.

To repeat against isolated test services, configure `TEST_DATABASE_URL`,
`TEST_TEMPORAL_ADDRESS` and immutable `TEST_SANDBOX_IMAGE`, then run:

```sh
uv run --no-sync python -m pytest tests/test_worker_process_loss.py -q
```

The test skips without actual PostgreSQL, Temporal and an image. Keep generated
configuration, logs and artifacts private; the worker bundle contains the supplied
database configuration. This is one bounded process-loss observation, not a general
recovery SLA, host-loss test, paid-provider reconciliation or release qualification.
