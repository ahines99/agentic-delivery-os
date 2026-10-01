# Automatic recovery after a publishing-worker exit

[ADR-032](adr/ADR-032-workflow-publication-recovery.md) adds one bounded recovery
activity after an uncertain publication. The production publisher, manifest admission,
approval checks, PostgreSQL persistence and Temporal workflow execute in the owned
test. A first worker process abruptly exits after a durable controlled HTTP effect;
a separately started worker resumes the same workflow after its heartbeat timeout.
The builder and publisher are not retried.

| Exit or changed condition | Required outcome |
| --- | --- |
| Branch accepted; no PR exists | `POLICY_BLOCKED`, recovery `UNKNOWN`; no PR creation |
| PR accepted; acknowledgement lost with process | Existing draft confirmed; normal CI gates resume |
| Final PR read accepted; process exits before persistence | Same PR/head/manifest recovered and stored |
| Approval expires after accepted PR and worker exit | `POLICY_BLOCKED`; no recovery publication write |
| PR head changes after accepted PR and worker exit | `POLICY_BLOCKED`; changed head never declared ready |
| Authenticated cancellation during publication | Cancellation acknowledged; no recovery activity scheduled |

The five initial abrupt-exit scenarios passed in **127.52 seconds** on 2026-09-30.
The expanded publication, manifest, authority, manual-acceptance, service and saved
replay selection passed **168 tests with four explicit Docker-profile skips in
38.15 seconds**. The final integration selection passed **13 tests in 163.82 seconds**,
including all five abrupt-exit cases with actual Temporal history assertions and
the CI/cancellation regressions. The histories confirm one publication, one recovery,
one heartbeat timeout and one candidate execution in each crash case. Cancellation
confirms cleanup and no recovery schedule. Ruff, formatting and mypy passed.
[Complete hosted CI at `f489947`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36754579549)
subsequently passed Python 3.12/3.13 (3,349 tests and 151 skips each), all 154 service
integration tests, builds and secret scanning. The feature was then installed through
the [verified idle upgrade](local-runtime-upgrade.md). Windows regression remains
running; this does not constitute a new live ticket or completed pilot.

The first combined run retained 12 passes and one cancellation test timeout. Its
15-second test deadline was shorter than Temporal's possible heartbeat-throttled
delivery interval for the new 20-second publication timeout. The corrected test
waits at most 25 seconds, within the workflow's unchanged 35-second execution limit;
it still requires acknowledged cancellation, an APPLIED command and no recovery/CI
schedule. The complete selection then passed as recorded above. No production
timeout or cancellation assertion was relaxed in response to that test failure.

Each successful case retains exactly one branch and one draft PR, and rereads storage
through a fresh database engine. Recovery receipts bind the original workflow and
manifest. Reconstructed Git tree objects are the only repository writes permitted
during recovery. Missing, duplicate, truncated, malformed, revoked, changed and
disappearing provider records have focused denial tests. Saved and newly generated
workflow histories are replayed.

All provider HTTP effects, candidate execution receipts and subsequent CI results
are owned fixtures. The final `HUMAN_REVIEW` state in these tests proves workflow
continuation under the fixture's CI outcome; it is not a new live ticket or real CI
check. The database is disposable; the live delivery database, historical tasks,
real App/Linear credentials and paid models are not used. This does not establish
surviving-worker fencing, arbitrary provider races, host/daemon loss or a human pilot.

Run with an isolated PostgreSQL database and Temporal address in the test environment:

```text
python -m pytest tests/test_temporal_publication_recovery.py tests/test_temporal_ci.py -q
```
