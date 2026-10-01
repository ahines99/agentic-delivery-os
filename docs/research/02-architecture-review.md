# Architecture research and decisions

Reviewed 2026-09-27. This review separates documented platform behavior from project design decisions. The attached blueprint is a vision, not an implementation inventory.

## Recommendation

Build one Python 3.12 package with a FastAPI entry point and separately started Temporal worker. Use Pydantic 2 contracts, SQLAlchemy 2 transactions, Alembic migrations and PostgreSQL. These process boundaries do not require independently deployed microservices. Keep providers behind narrow interfaces, but implement only the local fixture path first and Linear/GitHub for the connected MVP.

The strongest part of the proposal is auditable requirement-to-evidence delivery. Its main architectural risks are two competing workflow authorities, unsafe duplicate side effects, approvals that survive changed code, and interpreting an incomplete impact graph as proof of safety.

## Findings from primary sources

| Evidence | Implication for this project |
|---|---|
| Temporal distinguishes read-only Queries, asynchronous Signals and Updates that return acceptance/results. Validators can reject Updates before history recording. [Python message passing](https://docs.temporal.io/develop/python/workflows/message-passing) (accessed 2026-09-27). | An HTTP acknowledgement must not imply that approval was applied. Persist ingress requests, use stable command IDs, and report command disposition. Record rejected operator requests in the application audit log as well. |
| Activities can execute more than once; the Python guidance calls for idempotence and deliberate retry policies. [Error handling](https://docs.temporal.io/develop/python/best-practices/error-handling) (accessed 2026-09-27). | Every branch, sandbox and PR write needs a logical operation key and reconciliation. A database receipt alone cannot guarantee that an external write happened exactly once. |
| Workflow changes need replay-compatible versioning. [Python workflow versioning](https://docs.temporal.io/develop/python/workflows/versioning) (accessed 2026-09-27). | Pin workflow/config versions per run, replay saved histories in CI before worker upgrades, and retain compatible workers until old runs finish. |
| Python cancellation raises `CancelledError`; structured concurrency relies on propagating cancellation after cleanup. [Python 3.12 asyncio tasks](https://docs.python.org/3.12/library/asyncio-task.html) (accessed 2026-09-27). | Cancellation is an explicit product action with bounded cleanup, not merely deleting a task record or swallowing an exception. |
| PostgreSQL provides uniqueness and foreign-key constraints; isolation levels affect concurrent transaction behavior. [Constraints](https://www.postgresql.org/docs/18/ddl-constraints.html), [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html) (accessed 2026-09-27). | Enforce ingress and operation deduplication in the database. Use optimistic version checks for commands; retry full transactions where serialization conflicts require it. Application checks alone are insufficient. |
| SQLAlchemy sessions have transaction and concurrency boundaries. [Session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) (accessed 2026-09-27). | Use one session per request/activity transaction and never share an AsyncSession across concurrent tasks. |
| FastAPI supports modular routers and dependencies. [Bigger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) (accessed 2026-09-27). | Organize by domain modules without turning every module into a service. |
| Pydantic strict mode reduces automatic type coercion. [Strict mode](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/) (accessed 2026-09-27). | Validate provider/model responses as untrusted input; also enforce semantic policy invariants that schemas cannot establish. |
| Alembic autogeneration produces candidate migrations that require review. [Autogeneration](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) (accessed 2026-09-27). | Commit reviewed migration files; test upgrade from a fresh database. Never run speculative schema generation at application startup. |

## Changes to the original proposal

1. Move policy, secret handling, sandbox restrictions, budgets and evaluation fixtures ahead of the builder, not after the regression milestone.
2. Treat Temporal as the authority for a running workflow's lifecycle. PostgreSQL owns submitted specifications and command receipts, with an explicitly labeled workflow projection. Never independently advance the same state from both systems.
3. Make immutable specification, policy, plan, repository and evidence revisions first-class. Approval is authorization for a particular revision, never an unqualified Boolean.
4. Stop MVP success at a verified, review-ready PR. Human merge is mandatory for every tier; deployment is outside MVP. Observe a later human merge separately.
5. Begin repository intelligence with file/import/test relationships and provenance. Dynamic dispatch and unknown edges expand validation; they cannot justify skipping tests. Defer embeddings and graph databases.
6. Use three model contexts initially: requirements/planning, builder, independent reviewer. Deterministic checks establish policy and evidence completeness. More role names do not demonstrate independent verification.

## Alternatives and tradeoffs

Temporal adds an operational dependency and replay constraints. It is justified once workflows survive restarts and wait for clarification or review. A local pure-Python state validator remains useful for foundation tests; it is not a replacement for durable orchestration. A custom database queue would need leases, retry/cancellation semantics and replay design, so it is rejected for the connected path. Prefect remains viable for batch analysis but is not selected for this human-gated delivery workflow.

Use PostgreSQL relationship tables before pgvector or a graph database. Use local artifact storage behind an interface before object storage. Do not claim that a Docker container alone is a sufficient boundary for hostile tenant code; the initial execution scope is allowlisted repositories on a dedicated local runner.

## Required proof before connected execution

- Duplicate ingress, worker restart, lost external response and outbox redelivery produce one logical operation.
- A stale plan/PR-head approval is rejected; a head change invalidates current evidence.
- Cancellation stops new actions and records cleanup failures; no automatic rollback or merge occurs.
- Each criterion has current evidence with a reproducible command, exit result and artifact digest.
- History replay succeeds for supported workflow versions, and projection lag never changes authorization decisions.

These are implementation acceptance criteria, not claims that the present scaffold has passed them.
