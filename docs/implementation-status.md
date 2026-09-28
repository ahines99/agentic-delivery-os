# Implementation and verification status

Updated 2026-09-27 during end-to-end implementation. This is the current capability record;
the original milestone documents remain the release targets. Source code alone is not a passed
integration or production release gate.

## Implemented and exercised

- Validated operator/repository configuration; hashed bearer credentials, repository/role checks,
  bounded intake bodies, pause flag, idempotency keys and queued commands.
- SQLAlchemy tables and Alembic migrations on actual PostgreSQL; transactional inbox/outbox,
  immutable input revisions, sequenced audit projections, model reservations and usage settlement.
- Temporal worker and dispatcher; persisted planning/approval waits, stale command rejection,
  clarification, cancellation, duplicate suppression and replay tests across worker restart.
- Explicit reruns of eligible terminal attempts with a separate attempt/budget and retained prior
  spend; uncertain publication blocks rerun. Canonical stored commands are resolved and authorized
  before workflow signals are applied. Plan approval requires the reviewer role and an absolute
  decision deadline; repeated invalid signals do not extend it.
- Per-run configuration digests bind model, repository, budget and publication settings. A changed
  execution configuration fails the attempt and requires fresh planning/approval. Changed payloads
  for the same source ticket return conflict rather than creating parallel budget allocations.
  Projection idempotency checks include the complete audit event digest.
- Signed Linear webhook intake with workspace/team/assignee scope and payload/semantic deduplication.
  This is tested with signed fixtures, not a live Linear workspace.
- Real Anthropic structured generation for planner, builder and fresh reviewer; OpenAI Responses
  wire contract tested using a mock transport. No cached success is treated as a new paid call.
- Pinned Git snapshots and safe text-file edits; path/secret/sensitive-code rejection, original-test
  protection, conservative Python import impact analysis and mandatory full approved suite.
- Ephemeral non-root Linux Docker jobs without networking, credentials, host mounts or daemon socket;
  read-only root, bounded tmpfs, CPU/memory/PID/output limits, timeout and cleanup.
  Actual Docker tests cover memory, PID and disk exhaustion plus hostile PEP 517 dependency hooks.
- Independent baseline/candidate and criterion-specific pytest execution; immutable artifact digests;
  bounded repair loops; reviewer findings and a local candidate evidence manifest.
- GitHub App publisher with repository-scoped installation token, base/head checks, draft-only PRs,
  operation markers/reconciliation and token revocation. Contract tested, not live App authenticated.
  A final PR reread checks exact base/head revisions, repositories, branch references, open state
  and draft status before recording publication success.
- GitHub signed observation endpoint and separate stale/merged/closed publication record;
  Linear read/status adapter. These require live provider onboarding before a release claim.
- Evaluation schema, family/split validation, protected worker-input projection, isolated scoring,
  strict denominators, missing-task accounting and Wilson intervals. `delivery-eval` exports schemas,
  validates manifests and creates reproducible reports; no historical benchmark run exists.
- Pinned Compose development PostgreSQL/Temporal services, local CLI/API/worker entry points,
  tests and GitHub Actions quality/integration jobs.
- `/readyz` checks database readiness; authenticated `/operations` exposes repository-scoped
  workflow states, spending, and pending/exhausted dispatch summaries.

The latest complete local verification passed **163 tests** with `TEST_DATABASE_URL`,
`TEST_TEMPORAL_ADDRESS` and `TEST_SANDBOX_IMAGE` configured against actual Compose PostgreSQL,
Temporal and Docker. [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293)
passed all four checks on `d3fa44e`: Python 3.12, Python 3.13, PostgreSQL/Temporal/Docker,
and secret scanning. Packaging, clean wheel installation/migrations, Ruff, mypy and actionlint passed.
The [draft implementation PR](https://github.com/ahines99/agentic-delivery-os/pull/1) remains open for human review.

A [local backup/restore drill](local-backup.md) restored a real PostgreSQL dump into a new disposable
database with matching ten-table counts and Alembic revision, verified 26 artifact digests, and
removed only that disposable database. It does not establish Temporal/provider recovery.

## Recorded live development runs

These used the controlled synthetic customer fixture, not historical benchmark tasks. Credentials
were loaded from an explicitly authorized sibling project environment and never written to source.
Model spend comes from returned usage and the recorded rate card; it excludes infrastructure and
human effort. It is not a comparative performance claim.

| Run | Observed result | Model spend |
| --- | --- | --- |
| `4d89ec2c-d5d2-4a2d-b107-0864750d447c` | Durable live plan reached `PLAN_REVIEW`, then explicitly cancelled | $0.041415 |
| `81e980f4-7b25-4b1b-b964-322f2a28d748` | Local real build, new tests, verification, independent review; one attempt | $0.174500 |
| `79d5113b-2be7-462a-8179-260d832ccf9b` | Authenticated intake and approval through Temporal to a verified local candidate; stopped `POLICY_BLOCKED` at disabled publication | $0.184400 |
| `b3909403-fead-4093-ae60-c7d20cd3f181` | Real Compose-backed synthetic intake/approval/build/review; one attempt, `LOCAL_REVIEW_READY`, workflow `POLICY_BLOCKED` at disabled publication | $0.197655 |
| `d804b991-532d-4536-bfe4-bc7c5c4a02ff` | Final live Compose run with original-input/configuration/approved-plan bindings; one verified attempt, publication disabled | $0.192025 |

The latest candidate's manifest is `60c0d5f30afd7a55831da20c8f88ae5e783f3f6b4c22dda1ee1d8096434623e2`.
Raw artifacts stay under ignored `.local/artifacts`; no sensitive artifacts are published by default.
The successful candidate result is `LOCAL_REVIEW_READY`, not a merged or deployed outcome.

## Remaining release gates

1. Configure a GitHub App installation/private key for only the target repository, set branch
   protections without bot bypass, and exercise actual publication/head-change reconciliation.
   The user's authenticated CLI is used for maintaining this project, never as the product's PAT fallback.
2. Configure a Linear organization/team/worker, signing/API secrets, HTTPS callback and review state.
   Run actual delivery/replay/status fixtures. No authorized Linear workspace credentials were found.
3. Extend security qualification beyond the exercised memory/PID/disk/dependency-hook controls.
   Current Docker tests do not establish general runtime-escape resistance or hostile multi-tenant isolation.
4. Complete granular execution recovery, independent check-run ingestion, production identity
   hardening, telemetry export, retention/deletion and cross-system recovery drills. Terminal-attempt reruns
   and bounded human-decision waits are implemented; they do not replace these operational gates.
5. Curate and independently qualify 30+ historical tasks, then execute the frozen paired evaluation
   with human scoring. Manifest validation and one synthetic live demo cannot satisfy this requirement.
6. Meet the complete product P-01–P-12 and security acceptance gates before calling this an MVP pilot.
   Additional trackers/languages/profiles and release automation remain conditional future options.

Use [ADR-006](adr/ADR-006-verified-local-candidate.md) for the deliberate prepublication review
and draft-handoff refinement. This repository is an implemented controlled prototype, not a claim
of a completed production delivery platform.

See [provider onboarding](provider-onboarding.md) for the exact GitHub App and Linear inputs.
This project's protected `main` requires green CI and one approving review, including administrator
enforcement; force pushes and automatic merge are disabled. Product target repositories need
their own protections and live onboarding evidence.
