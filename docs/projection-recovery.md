# Recovering a closed workflow's read projection

`delivery-service recover-projection` repairs the database's workflow read projection from
completed `project` activities in retained Temporal history. This is a narrow repair tool:
it does not resume execution, retry providers, change a publication, refund/reset spending,
or reconstruct a lost database. Use [the operations runbook](runbook.md) for other incidents.

## Preconditions and scope

- Operate from the trusted control-plane environment with the intended private configuration,
  migrated database, Temporal namespace and artifact directory. The CLI uses that environment's
  access; it is not a public unauthenticated recovery endpoint.
- Confirm the workflow identity and preserve a database/artifact backup before repair. The
  existing work item and run row must exist. Never point a drill at an actual delivery attempt.
- The Temporal execution must be closed. Running executions and continuation outcomes are
  refused; the tool pins the described Temporal run ID when fetching history.
- Complete retained history must contain a contiguous sequence of completed projection
  activities starting at one. Merely scheduled, failed, or unrelated activities do not establish
  authoritative projection output. Missing history is a blocking condition, not permission to guess.

## Inspect, then apply

```sh
uv run delivery-service recover-projection --config config.local.json --workflow-id WORKFLOW_ID
uv run delivery-service recover-projection --config config.local.json --workflow-id WORKFLOW_ID --apply
```

The first command reports current and recovered state/sequence, Temporal run/status, history
digest and the current projection fingerprint. It leaves database projection rows unchanged,
but writes content-addressed intent/report artifacts. Inspect that report, the workflow identity,
and the expected final result before choosing `--apply`.

An apply invocation independently refetches and validates history; it does not reuse the earlier
preview's fingerprint. It locks the run and compares the projection observed before its own
history read against current state, sequence, specification digest, result and update time.
A concurrent projection change aborts the transaction. Inspect again rather than overriding it.

Repair inserts missing audit rows and restores the run's state, sequence, specification digest,
last supplied result, and update timestamp. Existing audit events must agree with authoritative
history, including their event fingerprints when present. Extra or contradictory audit events,
wrong workflow identities, and sequence gaps fail closed with no partial writes. Existing audit
timestamps are retained; reconstructed rows use the activity-completion time from Temporal.

Financial reservations/settlements, token counts, budget/configuration, commands, work-item
inputs and publication/provider records are outside the repair mutation. The latest non-null
projection result survives subsequent events that supply no result. Reapplying the same history
does not create duplicate audit rows or change an already repaired projection.

Keep the returned intent/report artifact digests with the incident record. The intent artifact
is written before database application; a failed apply can therefore leave an intent artifact
without a successful report. The artifact store verifies bytes by digest; an artifact alone
does not prove that the database transaction succeeded.

## Refusals and remaining limits

| Result | Next step |
| --- | --- |
| Running/continued execution | Wait for safe closure or use the appropriate workflow lifecycle; do not force the database terminal |
| History absent, incomplete or noncontiguous | Restore retained authoritative history or investigate retention/export; do not synthesize missing events |
| Fingerprint changed | Reinspect the current run and identify the concurrent update |
| Audit contradicts history | Preserve both sources and investigate corruption/identity/version mismatch; this tool deliberately refuses to overwrite contradictory evidence |
| Spending/publication mismatch | Reconcile provider and ledger records separately; projection repair cannot resolve an uncertain external side effect |

This is not granular candidate-activity recovery, a complete backup/restore drill, or production
retention policy. Workflow code/namespace/run provenance and trusted Temporal access remain
operational prerequisites. A corrected projection also does not imply a candidate was published,
merged or deployed.

## Reproducible verification

```sh
uv run python -m pytest tests/test_projection_recovery.py -m "not integration" -q
uv run python -m pytest tests/test_projection_recovery.py -q
```

The integration test requires `TEST_TEMPORAL_ADDRESS` and `TEST_DATABASE_URL` for disposable
services, as in the runbook. Without both, it explicitly skips. It creates a unique synthetic
workflow and records real `project` activity completions, then damages only that workflow's
database projection. Preview preserves the damage; apply reconstructs the missing audit/result;
a second apply is idempotent. Synthetic usage and publication records are checked unchanged.
No live model, Linear, GitHub publication or existing delivery workflow is involved.

Verified 2026-09-28: **11 tests passed** with actual local Compose PostgreSQL and Temporal
(`127.0.0.1:27233`). The database password was read from the private local password file and was
not logged. Unit cases cover completed-only history, wrong identities/gaps, compare-and-swap
conflicts, contradictory/extra audit events, rollback, preserved spending/provider records and
repeat repair. This is a local recovery drill; it does not assert a hosted CI result.
