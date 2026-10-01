# ADR-001: Temporal for durable delivery workflows

- Status: Accepted for target architecture; implementation is staged.
- Date: 2026-09-27
- Decision owners: Project maintainers

## Context

Delivery work crosses unreliable model, source-control and execution boundaries and may wait days for clarification. The blueprint requires restart recovery, bounded retries and auditable human decisions. A synchronous request handler or in-memory task cannot satisfy those requirements. At the same time, the foundation must remain small and runnable without claiming a completed distributed platform.

## Decision

Use Temporal's Python SDK for the durable workflow once the local foundation advances to persisted execution. Keep the domain transition rules pure and independently testable. FastAPI accepts commands; PostgreSQL stores specifications and ingress receipts; Temporal is the authority for accepted lifecycle transitions. SQL read models are sequenced projections. An inbox/outbox bridges database commits and workflow delivery without a distributed transaction.

All I/O, model calls, subprocesses and provider writes occur in activities. Workflow code stays replay compatible. Activities have bounded retries and stable logical operation keys. Ambiguous provider results require reconciliation. Human decisions bind immutable input and policy revisions, with exact commit and evidence digests for code review.

Use Updates for commands whose acceptance/result matters, Signals for external notifications and Queries for read-only workflow inspection, following [Temporal's Python message-passing contract](https://docs.temporal.io/develop/python/workflows/message-passing) (accessed 2026-09-27). HTTP receipt and workflow application are separate statuses.

## Consequences

Temporal adds infrastructure and deterministic replay constraints, but avoids building our own durable scheduler and human-wait machinery. Python worker deployments must use a documented versioning strategy and replay tests; see [workflow versioning](https://docs.temporal.io/develop/python/workflows/versioning) (accessed 2026-09-27).

Activities may run more than once, so orchestration durability does not remove adapter idempotency, budgets or external-write reconciliation. See [error handling](https://docs.temporal.io/develop/python/best-practices/error-handling) (accessed 2026-09-27). Durable history is also not the long-term artifact archive or an authorization boundary.

The initial repository setup can include domain tests, schemas and local service configuration without a wired worker. README status must distinguish those pieces from a tested durable workflow.

## Alternatives

- **Custom PostgreSQL state machine and queue:** fewer services, but requires lease recovery, retry scheduling, cancellation and versioning machinery. Rejected for the connected MVP.
- **Prefect:** reasonable for scheduled data processing; not selected for this lifecycle centered on external commands and human waits. Revisit for future analytical workers without replacing delivery authority.
- **Agent framework checkpointing alone:** useful within a bounded activity but does not establish the full delivery protocol or external side-effect semantics.
- **Microservices per agent:** operational cost exceeds the initial product need. Use module and process boundaries within one package.

## Acceptance tests before adoption is considered complete

Demonstrate restart recovery during a human wait; duplicate command and webhook handling; external write response loss; stale-head approval rejection; cancellation cleanup; bounded correction loops; and replay of a saved history after a compatible code change. Verify projection outage cannot authorize work. These are release gates, not assertions about existing code.
