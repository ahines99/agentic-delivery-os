# Agentic Delivery OS product specification

Status: approved planning baseline, 2026-09-27. This is the intended product contract; the repository foundation is not the completed MVP. The existing repository directory remains `agentic-delivery-engineer`.

Current refinements: [ADR-006](adr/ADR-006-verified-local-candidate.md) puts independent
review before publication and keeps the PR draft for human review/merge.
[ADR-025](adr/ADR-025-automatic-linear-delivery.md) adds outbound polling and explicitly
configured low-risk automatic plan approval. These supersede the original webhook-only
intake and automatic ready-for-review wording retained in the journey below.
The [live clear-ticket demonstration](live-automatic-delivery.md) passed; the full
release contract below remains broader than that one configured target.

## Purpose and users

Agentic Delivery OS converts bounded engineering tickets into tested pull requests with independently reviewed, commit-bound evidence. Humans retain product decisions and merge authority.

| User | Job to be done | Success evidence |
|---|---|---|
| Repository maintainer | Delegate a small, well-specified Python change and review the result | Useful PR, explicit criteria, reproducible checks, concise limitations |
| Engineering lead | Understand whether agent work improves throughput without increasing defects | Correctness, regressions, total human effort, elapsed time, and cost measured together |
| Platform operator | Configure permissions, stop work, and recover failures | Enforced policy, bounded execution, resumable workflow, attributable audit trail |
| Portfolio reviewer | Reproduce and inspect the engineering claims | Local setup, real integration demo, published evaluation method and unedited failure accounting |

The initial deployment is a single-tenant pilot operated by a repository owner on explicitly onboarded repositories. Enterprise multi-tenancy and unattended production operations are not implied.

## Release boundaries

| Release | Required result | Explicit exclusions |
|---|---|---|
| Repository foundation | Product/architecture/security/evaluation plan, strict domain contracts, deterministic policy and transition tests, safe local intake demo, health endpoint, CI | Live integrations, real model execution, persistent durable workflows, code-editing agents |
| MVP | Real Linear ticket becomes an isolated Python change and GitHub PR with independent review and acceptance evidence; human merges | Automatic merge/deploy, additional trackers/languages, multi-repository work, data/AI workers |
| Portfolio release | Repeatable integration demos, failure recovery evidence, bounded impact analysis, published historical-task benchmark and limitations | General claims of production readiness or enterprise isolation |
| Later expansion | Additional work profiles and integrations justified by evaluation | No automatic commitment to the entire vision |

The local JSON input path is a development and offline demonstration interface. It does not replace the Linear requirement for MVP completion.

## MVP scope

- One onboarded GitHub Python repository and one pinned base commit per run.
- Linear intake through authenticated, deduplicated webhooks; explicit repository mapping and operator opt-in.
- Low-risk documentation, tests, and localized software behavior changes with existing, runnable validation.
- Requirements/planning context, builder context, and fresh independent reviewer context. Test execution and evidence validation belong to trusted services rather than model self-reporting.
- One real model-provider implementation behind a small internal interface. Choose and record provider/model versions using development evaluations before the first live pilot.
- Durable workflow execution, persisted evidence, bounded retries and repair loops, cancellation, clarification, and audit history.
- A GitHub publishing broker creates/updates a branch and PR; builder containers do not receive publishing credentials.
- Source-linked acceptance matrix, test results, regression scope, policy findings, review findings, cost, and known limitations in each PR.
- Human-only merge. The MVP has no autonomous production deployment or rollback capability.

## Admission and risk

Every repository is onboarded with an approved base branch, supported toolchain, validation commands, dependency preparation procedure, protected paths, resource limits, and authorized operator identities. Commands declared by an untrusted ticket or changed repository file cannot expand permissions.

Risk derives from both the requested behavior and observed changes. Tier 0/1 may proceed within the configured scope. Tier 2/3 require human triage and are outside autonomous MVP implementation. Sensitive areas include authorization/authentication, payment or financial logic, secrets, production infrastructure, destructive data changes, and policy/CI controls. A documentation label or file extension does not establish low risk; tests and fixtures can execute code.

Missing acceptance criteria, material ambiguity, unsupported dependencies, inaccessible evidence, or a failing baseline produce an explicit pause or failure. The system does not manufacture product decisions, hide test failures, or downgrade risk to complete a run. Safe non-material assumptions must be visible in the plan and evidence package.

## User journey

1. The maintainer onboards a repository and assigns an eligible Linear ticket.
2. Intake verifies the event and records a stable work item. Repeated delivery attaches to the existing run rather than creating another PR.
3. Requirements analysis produces explicit criteria, unresolved questions, risk signals, and a plan tied to the base commit. A material question pauses work until an authorized response is recorded.
4. Policy admits or blocks execution. The trusted runner creates an isolated environment and verifies the baseline.
5. The builder makes a bounded change. The validator runs approved checks against the candidate commit; failures may enter a bounded correction loop.
6. After candidate validation and security checks, the publishing broker opens or updates a draft PR. A reviewer with fresh context sees the ticket, criteria, base, diff, repository context, and actual validation evidence. It produces evidence-backed findings and a recommendation without write or publishing authority.
7. An evidence gate verifies every criterion, required check, reviewer result, and policy decision against the current candidate. Only then does the broker mark the PR ready for human review and Linear move to the configured review status. Corrections update the same PR and invalidate obsolete evidence.
8. A human reviews and merges using repository controls. Observed merge/closure updates may be recorded separately; the system never reports deployment success from PR creation.

## Evidence contract

Each run records the work-item revision, acceptance-criteria version, base and head SHAs, policy version, model/provider configuration, tool/image versions, and validation environment. Each criterion has a planned verification method and references to actual result artifacts. Evidence includes execution status, exit code where relevant, command identifier, timestamps, and content digest. Passing, failing, skipped, flaky, missing, and not-applicable results remain distinguishable.

Model explanations can support interpretation but cannot substitute for execution evidence. Manual criteria require a named human decision; they remain unresolved until that decision exists. A full test suite passing does not prove absence of regressions. The PR must state which behavior was checked and which remains unverified.

A changed candidate head, relevant base, policy, or acceptance specification invalidates the previous readiness decision and applicable approvals. The system revalidates before declaring the new revision review-ready. Builder-generated tests cannot alter or replace trusted benchmark tests. The independent runner executes the candidate in a separate controlled environment.

## Acceptance scenarios

| ID | Scenario | Required observable result |
|---|---|---|
| P-01 | Clear, low-risk ticket | One candidate PR, complete criterion matrix, independent review, actual checks, and correct Linear review status |
| P-02 | Ambiguous required behavior | Clarification recorded and execution paused; no unsupported behavioral assumption |
| P-03 | High-risk ticket or newly sensitive diff | Policy blocks further unauthorized activity and identifies the reason; model approval cannot override |
| P-04 | Duplicate webhook or activity retry | Existing run/PR is reconciled; no duplicate PR or repeated externally visible action |
| P-05 | Worker crash during implementation/publication | Recovery resumes or safely reconciles from persisted state; ambiguous external outcomes are checked before retry |
| P-06 | Missing, failing, skipped, forged, or stale evidence | Candidate cannot become review-ready; PR report identifies the unresolved check |
| P-07 | Reviewer requests changes | At most the configured repair attempts run; new candidate gets fresh validation/review, then pauses or fails if unresolved |
| P-08 | Cancel or budget/time exhaustion | No new model/tool activity begins after cancellation is acknowledged; active work is terminated within the configured grace period and cleanup is recorded |
| P-09 | Repository prompt injection or secret access attempt | Tool/policy boundaries hold; attempted instruction is treated as untrusted content; credentials are not exposed |
| P-10 | Human merges or closes externally | Delivery observation records the actual external result separately from agent readiness; no invented deployment result |
| P-11 | Baseline already failing | Candidate cannot claim a clean regression result; baseline failure is recorded and routed for human triage |
| P-12 | Network/provider unavailable | Bounded retry/backoff, explicit failure or pause, recorded spend and recoverable state |

These are required integration acceptance tests for the MVP, not claims that the foundation already implements them.

## Completion and measurement

**Review-ready** means every in-scope criterion has current passing evidence (including a recorded authorized human decision for any manual criterion), required automated checks and policy gates pass, unresolved blocking review findings are absent, and the artifact is available to a human reviewer. A criterion awaiting required human verification stays visibly pending on the draft PR and blocks this gate. Human merge review remains separate and mandatory.

**Agent work complete** means the review-ready PR and auditable evidence have been handed off. **Delivered** means a human merged the change and any separately configured delivery verification succeeded. A terminal failed/cancelled run is complete as a workflow but is not successful delivery.

MVP release requires all applicable P-01 through P-12 scenarios passing, repeatable real Linear/GitHub demonstrations, no known unresolved control bypass, and evidence records with no missing required fields. Exact retry, time, token, and monetary ceilings are versioned configuration; every live run must have finite ceilings before it starts.

The portfolio release additionally publishes results on at least 30 real historical tickets, plus dedicated ambiguity, injection, and recovery fixtures. Freeze evaluation task selection and scoring before running the reported configuration; include failures and exclusions. Report task-level uncertainty and avoid extrapolating from a small convenience sample. The detailed evaluation protocol owns dataset splits, operational budgets, and pilot promotion thresholds.

Measure functional acceptance, regression rate, false-ready rate, clarification quality, recovery/idempotency, total model and infrastructure cost, elapsed time, human review/repair time, and time waiting for humans separately. Compare builder-only and independently reviewed configurations; do not assume more agents improve outcomes. Published claims require measured results and the exact configuration. No performance results exist at foundation setup.

## Sequence and expansion rules

Foundation contracts and control tests come first. Persistence/intake and controlled execution follow. Independent review/evidence and real PR publication complete the narrow vertical slice. Recovery, adversarial tests, and evaluation determine readiness for a pilot. Bounded Python impact analysis improves validation only after a full-suite baseline exists; retrieval or graph complexity must show measurable value.

Jira, GitHub Issues intake, additional languages, data/AI worker profiles, rich UI, production release automation, and Value Creation OS integration remain future options. Implementing three worker profiles is removed from the first portfolio-release requirement: one well-evaluated workflow is sufficient to prove the core engineering thesis. The [research review](research/01-product-review.md) documents the evidence and judgments behind these decisions.
