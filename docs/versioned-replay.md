# Saved Temporal workflow replay corpus

`tests/test_versioned_replay.py` replays three committed, explicitly synthetic
Temporal histories with the **current production `DeliveryWorkflow`**. These tests
run offline in the normal pytest suite: no Temporal server, database, provider call,
repository code execution, or credentials are needed. They also run in ordinary CI.

The histories were generated on a local Temporal development server by loading the
workflow source directly from commit
`21077431f5839fd17d1ac2581dd16f13c04b567a`, without altering that source. Its SHA-256
is recorded alongside each history's digest and event count in
[`tests/fixtures/replay/manifest.json`](../tests/fixtures/replay/manifest.json).
The generator used Temporal Python SDK 1.33.0 and server 1.32.0. The manifest records
those observed versions; future test runs replay using the project's installed SDK.

| Fixture | Recorded production workflow path |
| --- | --- |
| `plan-stale-approval-cancel` | Plan review, stale approval rejected through `resolve_command`/`command_status`, fresh cancellation applied, terminal `CANCELLED` |
| `ci-linear-handoff` | Plan approval, candidate/publication, `reconciled-ci-handoff-v1` patch marker, pending CI timer, ready CI, `finish_handoff`, terminal `HUMAN_REVIEW` |
| `ci-active-cancel` | Plan approval and publication, patch marker, cancellation during active `reconcile_ci`, activity cancellation acknowledgement, terminal `CANCELLED` |

All named activities are fake implementations used only during fixture generation.
Plan approvals, CI results, draft publication and tracker confirmation in these files
are **fabricated protocol inputs**, not evidence of real authorization, model work,
GitHub CI, or Linear updates. The Temporal events themselves were recorded by the
actual local server, not manually assembled. The normal replay tests do not execute
those fake activities; their recorded outputs drive deterministic replay.

The generator only fetches histories through handles it just created. Inputs use
synthetic ticket/repository identities, fixed placeholder digests, and no source
files, task answers or customer descriptions. Client/worker identity is explicitly
`synthetic-versioned-replay-worker`, avoiding machine usernames and hostnames. Test
checks inspect decoded payloads and reject common credential/local-path patterns;
that bounded scan is not a universal secret detector. The files were reviewed as
synthetic data before inclusion; do not replace them with actual customer histories.
Recorded timestamps, event IDs and generated run IDs are preserved for replay.

## Running and regenerating

Run the saved corpus without any services:

```text
python -m pytest tests/test_versioned_replay.py -q
```

An intentional incompatible activity-name mutation provides a negative control:
the replayer must report nondeterminism rather than silently accept the altered
command stream. Other tests check history hashes, terminal states, the CI patch
marker, timer polling, command rejection and cancellation acknowledgement.

Regeneration is a separate explicit maintenance action. Keep the pinned Git commit
available locally and start an isolated local Temporal development server, then run:

```text
python tests/fixtures/replay/generate.py --address 127.0.0.1:27233
```

The generator only accepts the listed loopback development endpoints. It loads the
old workflow in a temporary importable module, records the three scenarios with
synthetic activities, replays each with the current workflow, and writes fixture
files plus their manifest. It never imports production activities or uses provider
credentials. Generated server records may remain in that local development server;
the generator does not delete unrelated histories. Review changed JSON and rerun the
offline tests before replacing the corpus. Regeneration changes timestamps/run IDs;
ordinary CI uses saved fixtures rather than generating new ones.

## What this establishes

The saved corpus makes a previous commit's representative workflow command streams
repeatable regression inputs. At generation time, the workflow source at the pinned
commit and current working version had no behavioral difference. Accordingly this
does **not** demonstrate a successful upgrade across two different workflow designs.
It does test future changes against these saved command streams.

The corpus covers the **present** `reconciled-ci-handoff-v1` marker branch. It does
not supply an older, pre-patch history or exercise the absent-marker compatibility
branch. It does not prove activity implementation compatibility, database migration
safety, all failure histories, payload codec upgrades, worker-version routing, live
deployment rollback, or zero-downtime upgrades. The existing actual-service tests
remain separate evidence for restart/cancellation behavior. A deployment upgrade
claim still requires a supervised version-transition drill and operational evidence.
