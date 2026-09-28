# ADR-008: Active authorization and confirmed cancellation outcomes

Date: 2026-09-28. Status: accepted implementation decision. Scope: candidate execution and
worker-side authorization; no expansion of merge authority or benchmark eligibility.

## Problem and decision

An entry-time plan approval could expire while a long candidate continued running. A cancellation
path could also discard a build cleanup exception and project `CANCELLED` without confirming
successful activity cancellation. Both make terminal state weaker than the intended control.

The service worker now rereads its private configuration for authorization decisions. It checks
the current reviewer/repository role, approval time window, input revision and execution digest.
An absent/invalid configuration fails closed with a sanitized error. Storage, routing or artifact
root changes require a restart; an existing activity never silently switches its backend.

Candidate execution checks authorization before every new model or verification operation, on
the five-second heartbeat loop, and before returning readiness. A failed monitor cancels the build
task and awaits its cleanup. It never turns an expired approval into a renewed approval. Direct
embedded `Activities` callers must supply a settings provider to observe file changes; the service
CLI wires that provider by default. Static injected settings remain useful for controlled tests.

If publication completes while authorization changes, the observed publication is persisted before
the post-effect check fails. A remote write cannot be retroactively undone by an authorization
check; subsequent readiness remains denied and observed effects stay available for reconciliation.

Planning rechecks configuration after snapshot retrieval and after generation. Publication
rechecks after Linear preflight and before each new GitHub mutation; tracker handoff rechecks
its authorization and CI gate immediately before the mutation after its issue read. Read-only
reconciliation and installation-token revocation can finish after revocation so observed effects
and cleanup are retained. CI and handoff cannot report readiness after execution settings drift.

The candidate activity propagates a cleanup exception even when cancellation was requested.
Workflow patch `verified-cancellation-outcome-v1` reports `CANCELLED` only for a recognized Temporal
cancellation outcome. A concurrent activity failure instead yields `FAILED` with cleanup unconfirmed.
The authenticated cancel command is recorded as applied because its request was issued; that
disposition does not assert that cleanup succeeded. Old histories retain their recorded branch.

## Evidence and limits

[Actual cancellation drills](../active-cancellation.md) cover PostgreSQL, Temporal, Docker parent/
child termination, approval expiry, an injected cleanup acknowledgement error and history replay.
[Saved prior-commit histories](../versioned-replay.md) also replay after adding the new patch marker.
The drills use synthetic tasks/providers and make no historical benchmark or real daemon-failure claim.

Polling is not atomic authorization. An already issued provider call can finish or spend tokens
before cancellation reaches it; unknown operations retain their reservations. A frozen event loop,
unavailable database/daemon, host loss or repeated process cancellation can defeat the measured
grace period and remain operational failure cases. API and dispatcher processes still load their
configuration at startup: restart them for token/role rotation and admission changes. This worker
change does not establish immediate HTTP credential revocation or production identity hardening.

Operators should replace configuration atomically. Invalid intermediate JSON deliberately stops
protected work. A changed execution configuration requires a new attempt and fresh approval.
