# Implementation and verification status

Updated 2026-09-28 during continued controlled implementation. This is the current capability record;
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
  decision deadline; repeated invalid signals do not extend it. Approval use rechecks its expiry,
  current reviewer role/repository authorization, input revision and configuration before protected work.
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
- Independent baseline/candidate and criterion-specific pytest execution through an image-owned
  structured collector. The gate requires complete session/return markers, collected identities,
  setup/call/teardown phases, minimum counts and snapshot/command bindings; stdout summaries do not
  establish success. Strict candidate-manifest admission validates referenced artifact bytes and
  input/configuration/approved-plan/candidate/check/reviewer relationships before publication.
  Candidate code shares the collector interpreter: this closes named forgery/early-exit cases,
  not arbitrary semantic manipulation or inadequate tests. Independent behavioral oracles remain required.
- GitHub App publisher with repository-scoped installation token, base/head checks, draft-only PRs,
  operation markers/reconciliation and token revocation. Contract tested, not live App authenticated.
  A final PR reread checks exact base/head revisions, repositories, branch references, open state
  and draft status before recording publication success.
- GitHub signed observation endpoint and separate stale/merged/closed publication record;
  Linear read/status adapter. Signed check-run/check-suite observations durably invalidate readiness.
  The [CI gate](ci-evidence.md) binds numeric repository/head/producer/check identity, requires bounded
  authenticated REST reconciliation with matching complete snapshots and suite state, and uses
  generation CAS plus a 60-second cache. Workflow CI polling has an absolute deadline and cancellation.
  Linear review-state handoff is a separate activity after CI, with before/after authorization checks
  and intent/result artifacts; uncertain provider outcomes remain UNKNOWN. These are controlled
  transport/workflow tests; live product App/Linear onboarding remains required.
- Evaluation schema, family/split validation, protected worker-input projection, isolated scoring,
  strict denominators, missing-task accounting and Wilson intervals. `delivery-eval` exports schemas,
  validates manifests and creates reproducible reports; no historical benchmark run exists.
  [Curation preparation](evaluation-curation.md) now contains 36 pinned metadata candidates, all
  UNQUALIFIED, zero qualified/scored; proposed groups do not constitute frozen eligible splits.
  [ADR-007](adr/ADR-007-automated-benchmark-qualification.md) replaces human benchmark curator/scorer
  prerequisites with isolated agent passes and deterministic qualification. The new bounded
  qualification validator and `validate-qualification` CLI are implemented; local contract and Docker receipt checks pass.
  Worker-input export/scoring now validate qualification before snapshot reads or Docker execution.
  The real qualifier runner remains missing. `human_minutes` is nullable; reported human-time savings
  remain null. No actual agent
  qualification or candidate admission is claimed, and human effort/benefit remains unmeasured.
- Pinned Compose development PostgreSQL/Temporal services, local CLI/API/worker entry points,
  tests and GitHub Actions quality/integration jobs.
- `/readyz` checks database readiness; authenticated `/operations` exposes repository-scoped
  workflow states, spending, and pending/exhausted dispatch summaries.

The offline evaluation CLI also exposes [paired comparison](evaluation-comparison.md) and
[campaign preregistration](evaluation-campaign.md). These preserve missing-task denominators,
unmeasured human benefit, phase ordering and matched budgets; neither executes a campaign.
The standalone [coverage importer/ranker](coverage-contexts.md) binds hints to exact measurement
inputs and always requires full regression execution. Its real coverage JSON smoke uses synthetic
local code and does not establish a qualified historical measurement or C-arm result.
Scoring now preserves original tests/configuration and revalidates the frozen collection and
receipt bindings; contradictory success/regression records fail validation.

The latest complete local verification on 2026-09-28 passed **638 tests, three explicit Windows
skips**, in 173.22 seconds with actual PostgreSQL, Temporal and Docker. The skips cover two POSIX
FIFO regressions and unprivileged symlink creation; Linux CI exercises those platform cases.
Ruff check/format (137 files), mypy (58 source files), locked dependency validation, wheel build
and clean-wheel evaluation/operations/coverage imports passed. Qualification/scoring Docker tests
use explicitly synthetic agent/rights records and do not admit historical tasks. No extra model
spend or historical benchmark run occurred in this update.

The earlier complete local verification passed **163 tests** with `TEST_DATABASE_URL`,
`TEST_TEMPORAL_ADDRESS` and `TEST_SANDBOX_IMAGE` configured against actual Compose PostgreSQL,
Temporal and Docker. [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293)
passed all four checks on `d3fa44e`: Python 3.12, Python 3.13, PostgreSQL/Temporal/Docker,
and secret scanning. Packaging, clean wheel installation/migrations, Ruff, mypy and actionlint passed.
The [draft implementation PR](https://github.com/ahines99/agentic-delivery-os/pull/1) remains open for human review.

On 2026-09-28 a new complete local run passed **392 tests, zero skips**, in 107.40 seconds
with actual PostgreSQL, Temporal and Docker configured; Ruff check, format (116 files) and mypy
(52 source files) passed. A subsequent focused run passed 17 tests: 10 dispatch-scope and 7 actual Temporal CI/Linear tests,
including confirmed and UNKNOWN tracker outcomes, with 12 new tests overall. Current collection
is 405 after an additional real PostgreSQL CI concurrency test passed (two focused PostgreSQL tests). No full 405-test local run is claimed. The rebuilt wheel installed in an isolated environment
and applied packaged migration 0006. These are working-tree results, not a new hosted CI result.
Scoped runs included 27 collector tests (9 actual Docker), 39 existing collector regressions,
70 manifest unit/adapter tests plus one actual Docker producer fixture, 113 CI contract/API/storage
tests, 14 handoff activity tests and 5 actual Temporal CI workflow tests. These scopes overlap;
do not add them to the full-suite count. The collector image exercised was
`sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8`.

A [closed-projection recovery drill](projection-recovery.md) passed 11 tests with actual local
PostgreSQL/Temporal: preview, repair from completed history, race/conflict refusal and idempotence.
It preserved spending/publication records and does not establish active-candidate or whole-system recovery.

A [local backup/restore drill](local-backup.md) restored a real PostgreSQL dump into a new disposable
database with matching ten-table counts and Alembic revision, verified 26 artifact digests, and
removed only that disposable database. A fresh 2026-09-28 drill restored migration 0006, matched
12 table counts, verified 46 artifacts (140503 bytes), and removed its disposable database; the
109106-byte dump has SHA-256 `f6c1fc64c7450887119f512833896aee8229de3d74d8836942adce45c2bcd234`.
These drills do not establish Temporal/provider recovery.

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
| `d804b991-532d-4536-bfe4-bc7c5c4a02ff` | Earlier live Compose run with original-input/configuration/approved-plan bindings; one verified attempt, publication disabled | $0.192025 |
| `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322` | Fresh structured-collector Compose run, one attempt; strict manifest reference-chain validation passed, candidate `LOCAL_REVIEW_READY`, workflow `POLICY_BLOCKED` at disabled publication | $0.186240 |

The latest candidate's manifest is `16831b037bbe2afb4eb17cba179c71ae7691bce2ae1fe6c9f1e2fe820d16c98a`.
The exact live configuration and complete referenced evidence chain (three candidate files) were
validated; the local result is `.local/live-evidence-validation.json`. An earlier attempt in this
follow-up remained NEW before a model call when a 20-row unscoped outbox batch starved its command;
the development driver now dispatches its own workflow explicitly. This failure is retained as
operational evidence, not omitted from the development account.
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
4. Qualify the implemented check-run/suite ingestion and REST readiness gate with the live product App.
   Complete granular active-execution recovery, production identity hardening, full telemetry,
   retention/deletion and cross-system recovery. Closed projection repair, terminal reruns and bounded
   waits do not replace these operational gates.
5. Independently qualify 30+ historical tasks from a reviewed inventory, then execute the frozen paired evaluation
   with calibrated independent agent scoring and authoritative deterministic tests under ADR-007.
   Manifest validation and one synthetic live demo cannot satisfy this requirement. Human plan
   approval, pilot signoff and merge remain distinct unchanged controls.
6. Meet the complete product P-01–P-12 and security acceptance gates before calling this an MVP pilot.
   Additional trackers/languages/profiles and release automation remain conditional future options.

Use [ADR-006](adr/ADR-006-verified-local-candidate.md) for the deliberate prepublication review
and draft-handoff refinement. This repository is an implemented controlled prototype, not a claim
of a completed production delivery platform.

See [provider onboarding](provider-onboarding.md) for the exact GitHub App and Linear inputs.
This project's protected `main` requires green CI and one approving review, including administrator
enforcement; force pushes and automatic merge are disabled. Product target repositories need
their own protections and live onboarding evidence.

The [completion audit](completion-audit.md) retains all 29 backlog items, 12 product gates and
36 research recommendations, including the remaining acceptance and external prerequisites.

A bounded [operational metadata export](operations-export.md) was exercised against actual private
PostgreSQL for workflow `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322`; output SHA-256
`cac7f2b60b5a8def617cbb15939829cf920c82717347005a5472355241758ef6`.
It contains allowlisted metadata, not artifact bytes or secrets. This advances M4-03 only within
that scope; retention/deletion, a full telemetry service and cross-system recovery remain open.
