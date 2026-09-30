# Final project plan

Planning baseline: 2026-09-27. Product: **Agentic Delivery OS**. Existing workspace/repository
directory: `agentic-delivery-engineer`. This document integrates five independent research
reviews and supersedes conflicting recommendations in the preserved
[original handoff](reference/original-handoff.md). “Accepted” means selected for this
implementation plan, not a claim of user approval of a deployment or completed production work.

**Current status: implemented controlled prototype.** The milestones below preserve the
accepted release targets; they are not a current feature inventory. Consult
[implementation status](implementation-status.md) for exercised capabilities and open gates.
[ADR-006](adr/ADR-006-verified-local-candidate.md) refines the original publication sequence:
verify and independently review a local candidate first, then publish a draft that stays
draft for human review. [ADR-025](adr/ADR-025-automatic-linear-delivery.md) now permits
owner-configured automatic plan approval for eligible low-risk Linear tickets; other
work retains authenticated human plan approval. Every merge remains human.
This refinement supersedes the earlier automatic-ready sequence retained below.

## Product commitment

Implementation priority, updated after the owner's direction to avoid overengineering:
finish one usable Linear-to-GitHub delivery before extending benchmark infrastructure.
The immediate sequence is persistent automatic intake, GitHub App onboarding, a real
automatically approved eligible ticket producing a tested draft PR, and the Linear
review-status handoff. Outbound polling supplies local intake without a public tunnel.
Fix defects exposed by that path and keep setup and operation straightforward.
Retain credential isolation, finite budgets, current test/review evidence, explicit
plan-approval authority and human merge controls. Additional evaluation frameworks, impact-analysis experiments
and broader operational tooling wait until this path works. Existing evaluation code
and release targets remain; this changes implementation order, not reported results.

That immediate delivery path passed on 2026-09-30: PER-13 was automatically detected,
implemented and independently reviewed; App-authored PR #6 passed all required CI
checks, and Linear moved to In Review with one PR attachment. The local login service
also recovered during its CI wait without another attempt or model charge. See the
[bound live record](live-automatic-delivery.md). The installed scope is one protected
sample-repository branch; this closes the bounded clear-ticket demonstration, not
all operational, historical evaluation or portfolio release gates.

Build a single-tenant delivery control plane that takes a bounded Linear ticket for an
onboarded Python repository, produces an isolated change and GitHub pull request, independently
verifies the candidate, and gives a human a concise evidence package. All merges are human.
The differentiator is trustworthy delivery evidence and measured review benefit, not role count
or autonomy alone. The [product specification](product-spec.md) defines P-01 through P-12.

The first release supports risk tiers 0 and 1, one repository per run, one issue tracker,
one source-control provider, and one model-provider adapter. Tier 2/3 and unknown risk fail
closed for execution. Material ambiguity pauses work. The product does not promise perfect
regression detection or correctness from passing tests.

## Decisions closed by this review

| Topic | Decision | Reason and consequence |
| --- | --- | --- |
| Product identity | Agentic Delivery OS; keep local folder name | Covers eventual software/data work without unnecessary filesystem or remote renaming. |
| Initial model roles | Requirements/planner, builder, independent reviewer | Separation of duties with three contexts; verification, policy and budgets are deterministic services. |
| Application shape | Python 3.12 modular monolith | One package, separately runnable API/worker/runner processes as needed; no initial microservice fleet. |
| Durable execution | Temporal Python SDK | Timers, retries, cancellation, replay and long human waits; no synchronous whole-ticket endpoint. |
| Persistence | PostgreSQL, SQLAlchemy 2, Alembic | Immutable inputs, inbox/outbox, audit/evidence metadata, projections; Temporal owns workflow history. |
| Retrieval | File search + Python AST/imports + test/coverage mapping | Mark unknown edges; graph assists test selection, never proves full impact coverage. |
| Embeddings | Deferred until retrieval ablation demonstrates value | No pgvector or graph database in the foundation. |
| Isolation | Credential-free offline Linux container on controlled execution host | Fixed runtime profile, actual isolation preflight, separate dependency preparation and publishing brokers. |
| Credentials | Control-plane broker with repository-scoped short-lived GitHub App tokens | Builder cannot publish, merge, or obtain broker secrets. |
| Review/evidence | Current base/head, input/plan/policy revisions and artifact provenance | Changed inputs invalidate readiness; fresh model context alone is insufficient independence. |
| Completion | Workflow ends at `HUMAN_REVIEW` | Human merge/deployment observations are separate delivery status, not agent success inference. |
| Model selection | One adapter chosen in M1 using development evaluations | Record provider/model/config versions; no speculative model IDs or hardcoded current pricing. |
| UI | API/read models and PR evidence first | A dashboard is optional after the vertical slice and evaluation. |
| Security timing | Before first code execution | Risk policy, credential isolation, provenance and budgets are release prerequisites. |
| Evaluation timing | Fixtures and protocol now, real tasks during implementation | Publish 30+ historical cases only after frozen scoring and leakage review. |

The five reviews are [product](research/01-product-review.md),
[architecture](research/02-architecture-review.md), [security](research/03-security-review.md),
[evaluation](research/04-evaluation-review.md), and [delivery](research/05-delivery-review.md).
They link primary sources, distinguish factual findings from project choices, and identify
limitations. See the [ADRs](adr/) for durable decisions.

## Implemented baseline and honest boundaries

The repository now includes authenticated control-plane endpoints, PostgreSQL migrations and
inbox/outbox storage, Temporal planning/approval workflows, real model adapters, a bounded
builder/reviewer pipeline, Docker execution, and digest-verified artifacts. Recorded local
checks exercised a real Anthropic model and a synthetic customer task through durable intake,
plan approval, candidate validation and independent review. Its candidate result was
`LOCAL_REVIEW_READY`; publication was disabled, so the workflow ended `POLICY_BLOCKED`.

The credential-free `delivery` CLI still evaluates only supplied fixture metadata. It does
not invoke that pipeline or authorize execution. The API and worker are separate entry points;
use the [runbook](runbook.md) for their configuration and operation.

GitHub App publication and Linear integration code are contract/fixture tested. Authorized
Linear credentials now pass live read-only discovery, and local workspace/team/assignee/review-state
mapping is configured. Controlled real tickets passed signed intake, exact replay and persisted
clarification/plan-review paths through a temporary HTTPS gateway. The later PER-13 run
verified supervised outbound intake, App publication, exact-head CI and Linear status
handoff. Provider fault qualification and broader hosting remain open. OpenAI's
wire adapter is contract tested; the recorded live model runs used Anthropic. Tests of named
Docker controls do not establish general hostile-code isolation. Complete recovery, identity,
security and product acceptance gates remain open, as does agent-led qualification and scoring
of 30+ historical tasks under ADR-007. Actual human benefit remains unmeasured. No completed MVP, benchmark efficacy, merge or deployment is claimed.

The [implementation status](implementation-status.md) is the current capability record;
the [backlog](backlog.md) annotates progress without treating code presence as release acceptance.
The five original research reviews and the full milestone plan remain retained as design history.

[ADR-030](adr/ADR-030-pending-manual-acceptance.md) implements the existing manual
acceptance requirement: a verified automated portion may become a draft with explicit
pending human criteria, but cannot pass final readiness without authorized revision-bound
human decisions. The isolated candidate/manifest/publication portion is implemented;
the human-command and workflow integration is connected and under qualification. Existing automated
and historical evaluation profiles retain their current meaning.
The automated evaluation path now uses [ADR-011](adr/ADR-011-current-qualification-authority.md):
executed v2 qualification with current consumption authority and separate metered scoring grants.
Legacy records allow inspection only. Live development calibration and synthetic qualification
have completed, and five historical development tasks have passed qualification. Qualification of the
required corpus and full campaign execution remain open. See the
[calibration record](evaluation-calibration.md) and
[historical attempts](historical-development-attempts.md) for outcomes and their limits.

## Milestones and dependency gates

Effort ranges below are planning estimates for one experienced developer, not delivery dates.
Integration access, repository onboarding and benchmark curation are the main uncertainties.
Do not overlap a dependent capability before its safety gate passes.

| Milestone | Work and dependencies | Demonstrable exit | Estimate |
| --- | --- | --- | --- |
| M0 — Foundation | This repository setup; contracts, decisions, fixtures, tests and CI | Offline low-risk, ambiguous and blocked samples behave as documented; checks pass | Established in this setup |
| M1 — Durable ticket to plan | M0; PostgreSQL migrations/inbox/outbox, Temporal, authorized local commands, Linear signed intake, requirements/planner, model usage accounting | A real Linear ticket produces a persisted revision-bound plan; restart, duplicate event, clarification and stale command tests pass | 2–3 weeks |
| M2 — Controlled local change | M1; GitHub fetch broker, immutable snapshot, dependency preparation, runner preflight, patch tools, builder, baseline/candidate checks | A low-risk ticket changes a controlled Python repo; all sandbox escape/egress/resource/cancel checks pass on the actual host | 2–3 weeks |
| M3 — Independent PR handoff | M2; publishing broker, draft PR reconciliation, reviewer, evidence gate, bounded corrections, CI ingestion, Linear review status | Real ticket reaches `HUMAN_REVIEW` with exact-head evidence; stale/forged/missing evidence blocks handoff; agent cannot merge | 2–3 weeks |
| M4 — Reliable MVP pilot | M3; recovery/replay/adversarial suite, telemetry, operation reconciliation, export/retention, operator runbooks | Product P-01–P-12 pass; security gates pass; evaluation validation gate authorizes a restricted pilot | 1–2 weeks |
| M5 — Portfolio evidence | Start curation in M1; requires M4; bounded Python impact map, paired ablations, frozen historical evaluation, recordings | Published 30+ real-ticket report with denominators/uncertainty/failures/cost and reproducible demos | 2–4 weeks |
| M6 — Evidence-led expansion | Requires M5 results identifying a worthwhile extension | One extension at a time meets its own new threat model and evaluation gate | Separately scoped |

Plan approximately **9–15 developer-weeks after foundation**, then revise estimates from M1
actuals. A successful toy demo is not a substitute for any exit gate. M1 includes security
and evaluation work; they are not postponed to separate late phases.

Publication order is explicit: after candidate validation and security checks, create a
**draft** PR at `PR_OPEN`; run independent review and acceptance; mark ready/request human
review and update Linear only after `ACCEPTANCE_CHECK` passes. Correction loops update the
same PR identity and invalidate obsolete results. A failed run can leave a clearly labelled
draft with failure evidence; it cannot advertise readiness. This resolves the original
proposal's ambiguity about PR creation versus review completion.

## Work contracts and workflow

The [architecture](architecture.md) defines authority and storage; the
[state machine](state-machine.md) defines legal edges and target guards. PostgreSQL does not
overwrite authoritative workflow state. Every externally visible operation has a stable
logical identity and reconciles an unknown outcome before retrying. A deduplicated receipt
is distinct from an applied command. Use a new execution generation for deliberate reruns.

Every verification result must identify the criterion, exact repository revisions, producing
runner, command/environment, observed status, and digest of the collected artifact. An
approval also binds input/plan/policy/evidence versions, authenticated human, scope and expiry.
These extended fields and identity verification are M1/M3 implementation work; current local
records are deliberately smaller and never authorize remote work.

The model interface accepts structured messages, available tool schemas, output schema,
deadline, cancellation and per-call usage limits. It returns a validated result, provider
request identity, usage, model/config identity and a classified error. Provider adapters
declare unsupported capabilities rather than pretending all providers behave identically.
No orchestration framework is needed inside Temporal for the first three roles.

## Budget and operational policy

Before any connected run, load a versioned finite budget and reserve spend before making a
call. Defaults and evaluation-specific ceilings live in the
[evaluation methodology](evaluation-methodology.md). Persist billed usage, estimates, retries,
infrastructure usage and rate-table version separately. Missing pricing cannot become zero
cost. Human waiting is reported separately from active execution time.

[ADR-021](adr/ADR-021-required-evaluation-program-enrollment.md) requires a concrete enrolled
ledger and current matching program registry at evaluation preparation, calibration and
campaign execution entry points, including resumed work. Historical receipt inspection remains
separate; this does not migrate old ledgers or renew their execution authority. Incorporating
historical liabilities is still required before claiming a complete program spending limit.

[ADR-022](adr/ADR-022-legacy-ledger-archival.md) defines explicit legacy archival before
historical liability incorporation. It preserves original accounting and unknown reservations,
requires stopped older writers, and grants no new execution authority. The archive transition
and concrete metadata reader are implemented. [ADR-023](adr/ADR-023-pinned-legacy-program-liabilities.md)
adds a new versioned registry policy that reconstructs and pins archived liability before
prospective capacity is allocated. Live archival/import, full inventory attestation and cost
promotion remain unfinished; old policies and grants are not silently migrated.

Use trace/workflow/attempt/operation IDs across structured logs and metrics. Redact secrets
before export. Track queue/active/human-wait latency, cost per attempted and accepted task,
false-ready results, correction count, clarification, cancellations, cleanup failures,
duplicate suppression and provider errors. No model-private reasoning is an audit requirement.

The M4 operator runbooks must cover: provider outage and quota exhaustion; webhook redelivery;
unknown PR creation outcome; lost sandbox; stale head; expired/revoked credentials; failed
cleanup; database restore/projection rebuild; workflow code upgrades and replay; artifact
retention/deletion; emergency pause. Pausing stops new admission and allows authenticated
cancellation; it does not silently merge, delete branches, or roll back production.

## Evaluation and promotion

[ADR-024](adr/ADR-024-prospective-criterion-evidence-gates.md) defines explicitly selected
criterion evidence checks: complete validated dispositions for all assigned requirements and
passing criterion evidence for every declared-ready candidate. Joint passing coverage retains
all requirements in its denominator; documented failure is not passing acceptance. Existing
policies cannot acquire these checks retrospectively. Infrastructure, cost, operational and
human pilot gates remain separate.

[ADR-018](adr/ADR-018-prospective-readiness-reporting.md) defines prospective A/B readiness
from each arm's sealed candidate status before final scoring. Its journal policy must be
pinned before phase opening or allocation; it supplies neither promotion nor execution
authority. Missing outcome/readiness evidence remains visible in the full assigned denominator.

[ADR-016](adr/ADR-016-prospective-campaign-token-ceilings.md) accepts a prospective,
explicitly selected `agentic-historical-v2`: 500,000 input and 64,000 output tokens
per attempt, with unchanged USD 5 model, USD 1 infrastructure, 30-minute and USD 1,000
campaign ceilings. [Versioned contracts and consumers](protocol-v2-implementation.md)
are implemented; historical activation remains gated. Existing v1 contracts,
records, grants and costs are unchanged; new runs need explicit protocol selection,
matching calibrated configuration and finite authority. This is a material protocol
change, not a claim of identical experimental conditions or a passing campaign.

Treat independent review and impact analysis as hypotheses. Compare configurations under declared
matched budgets. Keep public-patch leakage and hidden tests out of campaign builder/reviewer context.
Score behavior, regressions and false readiness with deterministic checks and a calibrated automated
rubric. Actual human effort or benefit remains unmeasured unless observed; never invent human
reviewer identities, review minutes or productivity savings. Track infrastructure errors and safety
denials with explicit denominators; never discard difficult tasks to improve the headline.

On 2026-09-28 the user requested a hands-off, fully agentic benchmark workflow. Under
[ADR-007](adr/ADR-007-automated-benchmark-qualification.md), the protocol now requires two independent
agent qualification/scoring passes, immutable input/model/configuration/output provenance, and a distinct third
adjudication context for disagreement. Deterministic baseline/reference qualification runs three
times each; failed checks, unresolved risk/rights or missing evidence fail closed and cannot be
voted into success. This supersedes earlier human-curator/rubric prerequisites for benchmark work.
Human plan approval, pilot signoff and every product merge remain unchanged.

The [protocol](evaluation-methodology.md) retains target 36/minimum 30 tasks, at least three
repositories, grouped equal dev/validation/sealed-test splits, contamination controls, matched
finite budgets, operational safety and validation/false-ready promotion thresholds. The 36 staged
metadata records are UNQUALIFIED diagnostic candidates, not a valid campaign merely by inclusion.
All thresholds are targets; no historical benchmark result or measured productivity benefit exists.
The USD 1,000 campaign cap is not permission for unlimited or unapproved spend. Live GitHub App and
Linear access remain separate product-integration prerequisites.

## Main risks and responses

| Risk | Mitigation / decision trigger |
| --- | --- |
| Scope expands before a useful PR exists | M0–M4 gates; no additional worker roles/trackers/UI until measured MVP. |
| Agent tests repeat the implementation's mistake | Independent runner, withheld behavior tests, calibrated independent agent rubric under ADR-007, generated-test mutation checks; human benefit unmeasured. |
| Prompt injection or malicious repository script | Capabilities outside prompts; no secrets/egress in builder; host-level adversarial tests. |
| External write succeeds but response is lost | Stable operation identity, authoritative reconciliation, explicit UNKNOWN stop. |
| Review/evidence stale after branch changes | Exact revision tuple, check invalidation and new review attempt after terminal handoff. |
| Static graph misses dynamic Python behavior | Explicit unknown edges and conservative full-suite fallback. |
| Benchmark overstates general usefulness | Frozen task manifest/splits, contamination disclosure, paired comparisons, uncertainty and failures. |
| Cost or runtime grows through retries | Pre-call reservation, persisted global budgets, deadlines and bounded repair loops. |
| Local sandbox mistaken for hosted security | Single-tenant restriction; disposable execution VM before arbitrary/untrusted repositories. |

## Deferred scope and decisions reserved for implementation

Jira, GitHub Issues intake, JavaScript, Kubernetes, multiple model backends, pgvector,
cross-service call graphs, dashboards, AI/data/analyst workers, automated deploy/rollback and
Value Creation OS integration are future options. Three worker profiles are no longer a
portfolio prerequisite; one reliably evaluated path is sufficient. Keep the original vision
as a research direction, not a promise to build every component.

M1 records actual GitHub organization/repository, Linear workspace/team, model account/data
policy, execution host and operating budget. These are environment inputs, not unresolved
architecture. Licensing is intentionally not granted by this scaffold; the owner chooses
an open-source license before public distribution. A remote owner/name and secrets are not
guessed. These facts do not block the local plan or repository setup.

Next release work: onboard the GitHub App, complete durable Linear ingress and handoff, qualify the historical evaluation
corpus, and satisfy the remaining acceptance gates listed in
[implementation status](implementation-status.md). Durable storage, Temporal, model-driven local
execution and the controlled candidate path are implemented; follow that current status record
when interpreting the original milestone targets above.
