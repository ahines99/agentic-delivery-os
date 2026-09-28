# ADR-015: Bounded candidate cleanup after activity failure

Status: accepted for the single-host controlled runtime; broader recovery remains open.

## Context

An [actual worker-process-loss drill](../worker-process-loss.md) showed the production
workflow correctly failed after heartbeat loss without repeating candidate/model work,
but its validation container remained running. The killed worker could not execute
`DockerRunner.run`'s `finally` cleanup. Explicit test-parent removal exposed the gap;
it was not automatic recovery.

## Decision

After a non-cancellation candidate `ActivityError`, the workflow schedules a separate
trusted `cleanup_candidate` activity before terminal projection. The
`candidate-failure-cleanup-v1` Temporal patch preserves replay of earlier histories.
The candidate retains its one-attempt policy. No model or builder retry is introduced.

The activity binds its exact request identity to the calling Temporal workflow and
the stored repository. It can only contain resources; revoked build approval does
not prevent cleanup. There is no public cleanup endpoint or model-accessible tool.
The operator's configured Docker host remains the existing trusted execution boundary.

`DockerRunner.cleanup_run` requires a canonical workflow UUID, lists only containers
with both `agentic-delivery.managed=true` and the exact `agentic-delivery.run` label,
and accepts at most sixteen unique full Docker IDs. It inspects the complete set
before removal, checking exact IDs, labels and runner-generated names. Deletion uses
structured Docker arguments and only inspected IDs, never a shell command, broad
name filter, prune or volume enumeration. Every removed ID must subsequently be absent
and the workflow-scoped listing empty. Preflight receives the same workflow label as
the other delivery checks; default standalone preflight calls retain their old scope.

The helper has a twenty-second total bound and five-second command bounds, with the
existing one-MiB output limit. The activity has a twenty-five-second execution timeout,
thirty-second scheduling deadline and one attempt. A verified result is retained as
an immutable cleanup artifact and in terminal evidence. Any failure, timeout or invalid
result records `UNKNOWN` / `verified_absent=false`. The delivery workflow remains
`FAILED`; resource removal cannot establish candidate correctness or successful delivery.

## Limits and validation

This reconciles a killed worker's containers on one configured host. Label absence
is a point-in-time observation, not a durable fence against a partitioned but surviving
worker starting more work. Existing approval/configuration checks have no per-run
resource lease; adding one is outside this bounded change. Host/daemon loss, cross-host
Docker routing, provisioning uncertainty and universal cleanup timing are not solved.

Focused controls cover mismatched or duplicate identities, labels/names, malformed or
oversized listings, removal/absence failure and timeout. Actual PostgreSQL/Temporal/
Docker drills separately verify automatic cleanup and explicit cleanup uncertainty
after real process termination. Earlier orphan evidence remains retained. Saved old
Temporal histories and newly generated histories replay without candidate reexecution.
