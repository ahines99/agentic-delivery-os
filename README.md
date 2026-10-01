# Agentic Delivery OS

A governed agent-assisted delivery platform that aims to convert issue-tracker tickets
into tested, independently reviewed pull requests, with evidence and human control of merges.

**Status: implemented controlled prototype; complete MVP release gates remain open.**
The accepted implementation plan is [docs/plan.md](docs/plan.md). The project retains the
local directory name `agentic-delivery-engineer`; the product/package name is Agentic Delivery OS.

## What works today

**Verified automatic delivery.** [PER-13](https://linear.app/personal-portfolio-project/issue/PER-13/add-ordered-customer-id-helper)
was detected in Linear, planned, built, independently reviewed and published as
[PR #6](https://github.com/ahines99/agentic-delivery-os/pull/6). The PR passed all required
GitHub checks, and the ticket moved to Linear In Review with its PR attached. A second ticket,
[PER-14](https://linear.app/personal-portfolio-project/issue/PER-14/add-customer-sorting-with-an-explicit-direction),
paused for clarification, resumed after a ticket edit, and completed the same handoff
with [PR #7](https://github.com/ahines99/agentic-delivery-os/pull/7). The delivery-proof source
at `8413dc4` passed [full CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36668888799).
See the [live evidence and recovery record](docs/live-automatic-delivery.md).

Core guarantees, each backed by tests and recorded evidence:

- **Human-only merges.** No agent, publisher or workflow has a merge capability; PRs stay
  draft for human review ([ADR-002](docs/adr/ADR-002-separation-of-duties.md)).
- **Separation of duties.** The builder cannot approve its own work. A fresh reviewer
  context sees the ticket, approved plan, diff and permitted evidence, not the builder's
  conversation. The publisher holds narrow GitHub App credentials that models never see.
- **Revision-bound evidence.** Plan approval, test evidence, review, manual acceptance and CI
  bind to the repository, base/head revisions and policy version; stale or missing evidence
  blocks the handoff.
- **Isolated execution.** Candidates run in a pinned, credential-free Docker image with
  network, resource and filesystem controls ([security model](docs/security-model.md)).
- **Finite budgets.** Every workflow has token, cost, wall-time and repair-round ceilings;
  cost is reserved before each model call, and uncertain usage stays recorded rather than dropped.

The [automatic delivery mode](docs/automatic-delivery.md) adds outbound Linear detection
and owner-configured low-risk plan approval ([ADR-025](docs/adr/ADR-025-automatic-linear-delivery.md)).
Other work retains authenticated human plan approval. Explicit manual criteria wait for an
authenticated human decision ([manual acceptance](docs/manual-acceptance.md)).

The unreleased [Product Ops integration](docs/product-ops-integration.md) admits one signed,
approved work item and runs a constrained local documentation lane that stops at a human-only
local change request ([ADR-034](docs/adr/ADR-034-product-ops-documentation-handoff.md),
[record](docs/records/2026-09-30-product-ops-handoff.md)).

## Architecture

```text
Linear -> Requirements -> Risk policy -> Plan -> Isolated build
       -> Independent verification -> Evidence -> Human-reviewed GitHub PR
```

**Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy/Alembic, PostgreSQL, Temporal,
Docker, GitHub App, Linear, Anthropic.

PostgreSQL holds the inbox/outbox, command ledger, audit records and model usage ledger.
Temporal runs durable planning, approval, build, review, publication and handoff workflows.
See [architecture](docs/architecture.md) and the [ADRs](docs/adr/).

## Known limitations and open gates

- **Merge control relies on GitHub branch protection.** No component can merge, but the
  publisher's App token can write branches; the owner must keep the base branch protected
  with required reviews and checks. The service does not verify that configuration.
- **No human merge has been exercised yet.** PRs #6 and #7 were handed off as drafts for
  human review, and no real human manual-acceptance decision has been recorded; tests use
  scripted operator identities.
- **One onboarded sample repository.** The verified target is `demos/sample_repo` on the
  protected `delivery-workbench-v2` base branch. The installed source profile
  rejects common `pyproject.toml`, lockfile and `conftest.py` files, and there is no
  dependency preparation yet, so typical projects are not supported
  ([provider onboarding](docs/provider-onboarding.md)).
- **Local, Windows-hosted service.** Intake and CI observation use outbound polling;
  persistent HTTPS hosting and live signed post-merge callbacks are not configured.
- **Named controls, not a hostile-code guarantee.** The Docker checks establish named
  controls, not safety against arbitrary hostile code. Complete recovery, security and
  product acceptance qualification remain release gates.
- **Historical benchmark not run.** Five separately acquired development tasks have passed
  qualification; the 30+ task corpus is not qualified, and the 36 catalog candidates remain
  unqualified. No task has been scored and no campaign has run, so there are no benchmark results.
- **One live model provider.** The recorded live runs used Anthropic; the OpenAI adapter is
  contract-tested only.

See [implementation status](docs/implementation-status.md) for recorded runs, verification
boundaries and outstanding work, and the [full completion audit](docs/completion-audit.md)
for every M0–M5 backlog item, product gate and research recommendation.

## Local quickstart

Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/) are required.
No credentials or Docker are needed for the offline intake fixtures.

```sh
uv sync --extra dev --locked
uv run delivery demos/sample_tickets/low-risk.json
uv run delivery demos/sample_tickets/ambiguous.json
uv run delivery demos/sample_tickets/high-risk.json
```

The samples produce `READY`, `NEEDS_CLARIFICATION`, and `POLICY_BLOCKED`. `READY` means only
that supplied fixture metadata passed intake checks; no model, code execution, or PR occurs.
For the actual control plane, follow the [local runbook](docs/runbook.md) to configure
PostgreSQL, Temporal, a fixed sandbox image, operator authentication, and an authorized model.
Start the API, worker, dispatcher and enabled monitor with `delivery-service run`.
The API includes authenticated work-item, workflow, rerun and command endpoints; `/healthz` is
liveness only, `/readyz` checks the database, and authenticated `/operations` summarizes scoped
state, spending and dispatch. Model-backed runs spend tokens and require explicit data authorization.
Publication remains disabled by default, and there is no personal-token fallback.

To exercise the installed local service, create a new Backlog ticket in the Personal Project
Portfolio team, leave it unassigned, include `Repository: agentic-delivery-os`, add the
`delivery-ready` label, and state clear acceptance criteria for a change within `demos/sample_repo`. Detection
runs every 30 seconds; keep the machine awake and Docker Desktop running. Additional
repositories require [onboarding](docs/provider-onboarding.md). The
[webhook gateway](docs/linear-ingress.md) supports both providers when public callbacks
are wanted.

### Quality checks

```sh
uv run --no-sync python -m ruff check .
uv run --no-sync python -m ruff format --check .
uv run --no-sync python -m mypy
uv run --no-sync python -m pytest -n auto --dist worksteal
```

Integration tests explicitly skip without the runbook's service variables.
`delivery-eval` provides offline schema export, structural validation, legacy record inspection
and paired trial reporting; see [the evaluation workspace](evals/README.md). Current qualification
and campaign APIs require a trusted authority; the offline CLI cannot supply it.
These commands do not execute a benchmark or authorize spending.

## Evaluation status

The [historical candidate catalog](docs/evaluation-curation.md) contains 36 real
metadata-only candidates; none is represented as a qualified or scored task. Benchmark
qualification and scoring follow the owner's hands-off preference through
[independent agent reviews and executable checks](docs/adr/ADR-007-automated-benchmark-qualification.md).
The worker and scorer require current authority over executed v2 qualification records; scoring
also requires its own metered spending grant. Legacy records allow inspection only. Absent
human observations remain unmeasured. This does not change the configured plan-approval
authority, human merges or pilot signoff.

- An owned development fixture passed the complete synthetic qualification path: 13 actual
  Docker operations, two independent model reviews and reconstructed authority validation.
  Synthetic fixtures remain barred from historical admission, worker export, scoring and
  campaign use ([recorded qualification](docs/evaluation-calibration.md#completed-synthetic-qualification)).
- Protected acquisition and v2 import reached actual execution for seven historical
  development candidates. Five passed all deterministic checks, two independent model
  reviews each and authority validation; rejections and a truncated review whose cost was
  reconciled are retained ([recorded attempts](docs/historical-development-attempts.md)).
- A separately frozen final-scorer configuration passed all five owned development anchors
  ([calibration evidence](docs/semantic-calibration.md), not historical accuracy), and a
  separate [owned adjudicator calibration](docs/semantic-adjudication-calibration.md#recorded-live-owned-calibration)
  passed all five dispute anchors. Historical adjudication and campaign execution remain open.

## Verification history

The installed service received cancellation, response-recovery, intake, manual-acceptance,
bounded-container-lifetime, attachment-response and terminal-command recovery changes,
automatic existing-publication recovery, operation logging and lifecycle metrics and
provider/cleanup diagnostic exports through `63f25f2`. The
[latest local upgrade record](docs/local-runtime-upgrade.md) separates installed features,
completed checks and pending release qualification.

Before live publication was enabled, the recorded local suite at `3956b29` passed 1997 tests
with actual PostgreSQL, Temporal and Docker, and
[a recorded hosted CI run passed](https://github.com/ahines99/agentic-delivery-os/actions/runs/36502328714)
on Python 3.12/3.13, real service integration and secret scanning. A synthetic customer task
then reached `LOCAL_REVIEW_READY` and stopped at `POLICY_BLOCKED` because publication was
disabled. Controlled real Linear tickets subsequently passed signed webhook intake, exact
signed replay and persisted `NEEDS_CLARIFICATION`/`PLAN_REVIEW` states before the automatic
runs above. The original proposal remains preserved in
[docs/reference/original-handoff.md](docs/reference/original-handoff.md).

## Project map

| Path | Purpose |
| --- | --- |
| [docs/plan.md](docs/plan.md) | Accepted scope, sequencing, decisions, completion gates |
| [docs/implementation-status.md](docs/implementation-status.md) | Current capabilities, recorded live checks, and remaining release gates |
| [docs/runbook.md](docs/runbook.md) | Local service setup, authenticated operations, and recovery |
| [docs/product-spec.md](docs/product-spec.md) | Product requirements and MVP acceptance |
| [docs/architecture.md](docs/architecture.md) | Components, contracts, storage, recovery |
| [docs/security-model.md](docs/security-model.md) | Trust boundaries and execution controls |
| [docs/evaluation-methodology.md](docs/evaluation-methodology.md) | Reproducible evaluation protocol |
| [docs/evaluation-campaign.md](docs/evaluation-campaign.md) | Qualified dataset/arm preregistration and frozen scheduling |
| [docs/semantic-consumption.md](docs/semantic-consumption.md) | Read-only completed review and adjudication evidence under current authority |
| [docs/completed-attempt-reporting.md](docs/completed-attempt-reporting.md) | Whole-attempt reconstruction, retained failures and exact adjudication accounting |
| [docs/campaign-dispatch.md](docs/campaign-dispatch.md) | Serial attempt execution, optional adjudication and durable uncertainty fencing |
| [docs/campaign-phase.md](docs/campaign-phase.md) | Bounded scheduling under the original phase authorization |
| [docs/campaign-accounting.md](docs/campaign-accounting.md) | Consistent metadata reads, retained reservations and exact preparation inventories |
| [docs/campaign-reporting.md](docs/campaign-reporting.md) | All-assignment proof consumption, frozen readiness and explicit missing evidence |
| [docs/coverage-contexts.md](docs/coverage-contexts.md) | Revision-bound measured coverage hints and uncertainty |
| [docs/active-cancellation.md](docs/active-cancellation.md) | Actual workload cancellation, expiry and cleanup-failure drills |
| [docs/correction-loop.md](docs/correction-loop.md) | Controlled rejection, fresh repair evidence and exhausted-loop tests |
| [docs/candidate-arms.md](docs/candidate-arms.md) | Shared builder-only and independent-review candidate engine |
| [docs/worker-process-loss.md](docs/worker-process-loss.md) | Actual killed-worker cleanup and explicit uncertain outcomes |
| [ADR-014](docs/adr/ADR-014-campaign-execution-budgets.md) | Separate immutable qualification and frozen campaign execution budgets |
| [docs/protocol-v2-implementation.md](docs/protocol-v2-implementation.md) | Explicit prospective protocol contracts with strict v1 compatibility |
| [docs/single-attempt-coordinator.md](docs/single-attempt-coordinator.md) | Shared-account candidate, deterministic and two-scorer composition |
| [docs/campaign-journal.md](docs/campaign-journal.md) | Durable assignment order, current phase decisions and sealed-case exposure |
| [docs/historical-merge-linkage.md](docs/historical-merge-linkage.md) | Explicit first-parent merge metadata with unchanged current authorization |
| [docs/semantic-adjudication-execution.md](docs/semantic-adjudication-execution.md) | One separately authorized third review of sealed disagreements |
| [docs/linear-ingress.md](docs/linear-ingress.md) | Bounded Linear-only gateway and temporary live intake evidence |
| [ADR-016](docs/adr/ADR-016-prospective-campaign-token-ceilings.md) | Prospective explicit token ceilings with unchanged financial caps |
| [ADR-015](docs/adr/ADR-015-bounded-candidate-cleanup.md) | Bounded trusted cleanup following candidate activity failure |
| [docs/operator-rotation.md](docs/operator-rotation.md) | Restart-based HTTP token rotation and paused-admission rehearsal |
| [docs/artifact-retention.md](docs/artifact-retention.md) | Read-only artifact reachability planning and required scope |
| [docs/qualification-runtime.md](docs/qualification-runtime.md) | Metered preflight and twelve-run deterministic checks with safe resume |
| [docs/qualification-controller.md](docs/qualification-controller.md) | Complete private qualification execution, independent reviews and resume |
| [docs/qualification-admission.md](docs/qualification-admission.md) | Executed evidence, current consumption authority and legacy inspection |
| [docs/scoring-execution.md](docs/scoring-execution.md) | Separate candidate scoring grants, accounting and revocation |
| [docs/campaign-scoring.md](docs/campaign-scoring.md) | Explicit frozen-arm scoring on existing shared attempt accounts |
| [docs/campaign-allocation.md](docs/campaign-allocation.md) | Canonical per-attempt capacity on one pinned ledger |
| [docs/campaign-candidate.md](docs/campaign-candidate.md) | Metered A/B candidate generation on existing attempt accounts |
| [docs/candidate-inspection.md](docs/candidate-inspection.md) | Read-only reconstruction under fresh consumption authority |
| [docs/semantic-scoring-context.md](docs/semantic-scoring-context.md) | Protected candidate evidence and structurally validated scorer findings |
| [docs/semantic-scoring-examples.md](docs/semantic-scoring-examples.md) | Five original subjects with separate expected outcomes |
| [docs/owned-semantic-runtime.md](docs/owned-semantic-runtime.md) | Actual bounded owned-example checks without historical admission |
| [docs/owned-semantic-context.md](docs/owned-semantic-context.md) | Current owned-example evidence without historical task impersonation |
| [docs/semantic-calibration.md](docs/semantic-calibration.md) | Separate five-case final-scorer calibration and immutable receipts |
| [docs/semantic-execution.md](docs/semantic-execution.md) | Two calibrated initial scorers with agreement and unresolved outcomes |
| [docs/semantic-adjudication-calibration.md](docs/semantic-adjudication-calibration.md) | Separate metered adjudicator calibration and current read-only validation |
| [docs/semantic-owned-adjudication.md](docs/semantic-owned-adjudication.md) | Actual owned runtime evidence with unchanged hypothetical peer findings |
| [docs/scoring-inspection.md](docs/scoring-inspection.md) | Current read-only reconstruction of completed deterministic scores |
| [docs/semantic-file-pool.md](docs/semantic-file-pool.md) | Pure lossless context codec; model wire integration remains pending |
| [docs/semantic-prompt-versions.md](docs/semantic-prompt-versions.md) | Explicit prompt selection preserving previous artifact bytes |
| [docs/semantic-adjudication-contracts.md](docs/semantic-adjudication-contracts.md) | Separate authored dispute contracts and conservative structural merge |
| [docs/qualification-v2.md](docs/qualification-v2.md) | Protected semantic evidence, independent reviews and adjudication |
| [docs/qualifier-prompt-contract.md](docs/qualifier-prompt-contract.md) | Explicit finding and citation requirements with prompt provenance |
| [docs/evaluation-calibration.md](docs/evaluation-calibration.md) | Executed development cases and recomputed calibration metrics |
| [docs/synthetic-preparation.md](docs/synthetic-preparation.md) | Owned development provenance without invented historical records |
| [docs/synthetic-preparation-runtime.md](docs/synthetic-preparation-runtime.md) | Bounded five-case Docker preparation with no model calls |
| [docs/synthetic-import.md](docs/synthetic-import.md) | Protected authored-case import and exact data authorization bindings |
| [docs/historical-import.md](docs/historical-import.md) | Offline protected historical import with complete source inventory checks |
| [docs/historical-import-v2.md](docs/historical-import-v2.md) | Derived historical import with exact linkage and current data authorization |
| [docs/historical-acquisition.md](docs/historical-acquisition.md) | Bounded public GitHub baseline acquisition into protected evaluator storage |
| [docs/historical-requirements.md](docs/historical-requirements.md) | Protected issue bodies with bounded provider-reported edit history |
| [docs/historical-reference-derivation.md](docs/historical-reference-derivation.md) | Exact protected production deltas and whole-file test relocation |
| [docs/src-layout-verification.md](docs/src-layout-verification.md) | Bounded operator-selected source imports in the trusted collector |
| [docs/historical-input-provenance.md](docs/historical-input-provenance.md) | Source, issue and provider evidence for finite historical processing |
| [docs/baseline-failure.md](docs/baseline-failure.md) | Actual failing-baseline checks that stop before model or candidate work |
| [docs/synthetic-calibration-cases.md](docs/synthetic-calibration-cases.md) | Five original development cases with separately frozen expectations |
| [docs/calibration-subjects.md](docs/calibration-subjects.md) | Inert review subjects separated from safe executed fixtures |
| [docs/qualification-inputs.md](docs/qualification-inputs.md) | Review inputs reconstructed from completed ledger evidence |
| [docs/model-request-forecast.md](docs/model-request-forecast.md) | Pure exact reservation forecasting without model effects |
| [docs/model-failure-reconciliation.md](docs/model-failure-reconciliation.md) | Cost-only accounting for a narrowly evidenced failed evaluation call |
| [docs/provider-failure-operations.md](docs/provider-failure-operations.md) | Provider failure diagnosis, retained uncertainty and recovery limits |
| [docs/qualification-preparation.md](docs/qualification-preparation.md) | Offline evidence preparation without admission or spending |
| [docs/evaluation-execution-store.md](docs/evaluation-execution-store.md) | Separate evaluation accounts, immutable usage and checkpoints |
| [docs/model-operation-receipts.md](docs/model-operation-receipts.md) | Bound model provenance and retained uncertain outcomes |
| [docs/versioned-replay.md](docs/versioned-replay.md) | Saved prior-commit Temporal histories and replay limits |
| [docs/backlog.md](docs/backlog.md) | Dependency-ordered implementation issues |
| [docs/research/](docs/research/) | Five independent research reviews and an automated-curation feasibility study |
| [docs/adr/](docs/adr/) | Architecture decision records |
| `src/agentic_delivery/` | Control plane, provider adapters, candidate pipeline, runner, and evaluation harness |
| `demos/sample_tickets/` | Credential-free intake fixtures |
| `tests/` | Unit, contract, and opt-in PostgreSQL/Temporal/Docker integration tests |

See [contributing](docs/contributing.md) for development and
[demo guide](docs/demo-guide.md) for verified behavior and planned demonstrations.
Synthetic live checks are development evidence, not benchmark results or cost-saving claims.
