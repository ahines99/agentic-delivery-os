# Dependency-ordered implementation backlog

This is the issue-ready execution sequence for [the accepted plan](plan.md). IDs are stable local references, not hosted issue numbers. The rows preserve the original acceptance targets; they are not a completion ledger. The controlled prototype now implements substantial M1–M5 capabilities, but full milestone release gates remain open. Scope or architecture changes require the plan and relevant ADR to change together.

## Current status annotations

**Current implementation progress:** the [PER-13 live path](live-automatic-delivery.md)
completed automatic Linear detection, App publication, required CI and the correct
review-state handoff. Outbound observation of PR closure/merge is also installed
under [ADR-027](adr/ADR-027-outbound-publication-observation.md), without a public
tunnel. Planning cancellation, provider response recovery and an actual live
backup/restore drill have subsequent verification records. The manual-criterion
handoff is implemented and installed under [ADR-030](adr/ADR-030-pending-manual-acceptance.md);
only scripted operator decisions have exercised it, so a real human manual-acceptance
decision remains unexercised. Remaining qualification and portfolio release targets
below stay open.

Refer to [implementation status](implementation-status.md) for recorded evidence and remaining gates. Code presence, mock-provider tests and one synthetic live run do not close an entire backlog item.

| Milestone | Implemented/exercised progress | Acceptance still outstanding |
| --- | --- | --- |
| M0 | Package, contracts, fixtures, documentation; hosted quality/integration/secret-scan CI passed | Ongoing regression checks |
| M1 | Authenticated local intake/commands, real PostgreSQL and Temporal, model-assisted plans, plan approval, usage ledger; Linear signed-fixture tests | Broader provider fault qualification and complete identity, approval expiry/revocation and operational hardening; actual onboarding/intake/status are verified |
| M2 | Real synthetic build, fixed Docker runner, baseline/candidate/criterion tests and immutable artifacts | Broader dependency/resource/escape probes and granular execution recovery |
| M3 | Fresh independent model review and `LOCAL_REVIEW_READY`; controlled rejection/repair/exhaustion checks; shared A/B candidate engine; GitHub App publishing/observation contracts and Linear adapter | Live App draft publication, exact-head CI and Linear handoff passed; broader provider reconciliation faults, signed callbacks and historical A/B execution remain |
| M4 | Restart/replay and named failure paths; actual killed-worker cleanup or explicit UNKNOWN; local restore/projection drills and bounded private PG metadata export | Complete P-01–P-12, distributed fencing, daemon/host-loss, adversarial/retention/backup gates and validation qualification before pilot |
| M5 | Evaluation schema/scoring/leakage controls, 36 UNQUALIFIED metadata candidates, five separately acquired qualified development tasks and conservative Python impact analysis; schema-3 frozen execution budgets | Independently qualified 30+ historical tasks and execution of the implemented campaign/scoring tooling under the frozen paired protocol and ADR-007; no historical scoring or campaign exists |
| M6 | Retained future options | Evidence-led scope decision before implementation |

[ADR-006](adr/ADR-006-verified-local-candidate.md) supersedes the original publication order below: verification/review happen locally before draft publication, and a human controls readiness and every merge. The recorded durable synthetic run stopped `POLICY_BLOCKED` at disabled publication after producing a verified local candidate.

[ADR-007](adr/ADR-007-automated-benchmark-qualification.md) records the user's hands-off benchmark
preference: qualification/scoring uses two independent agent passes, a distinct adjudicator for
disagreement and authoritative three-repeat baseline/reference execution evidence. Unresolved
rights/risk/evidence fails closed. This supersedes human benchmark reviewer-name requirements;
all original 36 candidates remain UNQUALIFIED. Five separately acquired development tasks
passed qualification; no historical scoring or campaign has run. Actual human effort/benefit
is unmeasured, not fabricated.
Plan approval follows ADR-025; pilot signoff and product merges remain human controls.

Each implementation issue must identify its owner, dependencies, criterion IDs, test evidence, risk, and recovery behavior using the repository issue template. Estimates should follow the first vertical slice; the plan does not commit to speculative delivery dates.

## M0 — Foundation

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M0-01 | Accepted product, architecture, security, evaluation and ADR baseline | None | Working/planned boundaries are explicit; five research reviews are traceable; original handoff is historical input |
| M0-02 | Python package, contracts, lifecycle and policy predicates | M0-01 | Unknown fields/schema and illegal transitions rejected; missing/stale/failing evidence and builder self-review cannot pass tested structural gates |
| M0-03 | Offline fixtures, health API, lockfile, checks and contribution assets | M0-02 | Three fixture outcomes reproducible; lint/format/types/tests pass locally; hosted CI passed for 3.12/3.13 and actual service integrations |

Gate: a clean checkout reproduces the foundation and documents its limitations. No live provider or isolation claim is made.

## M1 — Durable intake and requirements

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M1-01 | Versioned runtime configuration and repository onboarding | M0-03 | Allowlisted provider/repository IDs, base branch, command profiles, protected paths, operator roles, finite budgets and secret references validated; unknown config denied |
| M1-02 | PostgreSQL schema/migrations, inbox/outbox and immutable input records | M1-01 | Atomic receipt/enqueue; unique delivery/semantic keys; migrations tested against real PostgreSQL; duplicate and rollback/crash cases preserved without double processing |
| M1-03 | Temporal workflow, workers and projection reconciliation | M1-02 | Deterministic replay; activity side effects isolated; worker restart and duplicate signal tests; state authority follows ADR-001; workflow/version deployment process documented |
| M1-04 | Authenticated Linear webhook and provider reconciliation | M1-02, M1-03 | Raw-body signature/freshness and workspace authorization; valid duplicates accepted; tampered/stale/replayed/out-of-order events safe; provider IDs cannot select arbitrary network targets |
| M1-05 | Model-provider selection, adapter and usage ledger | M1-01, M1-03 | One real provider selected using recorded development evaluation; structured outputs/errors/timeouts tested; finite per-call budgets and reservation/accounting enforced; no success-only stub |
| M1-06 | Revisioned requirements/planning, risk triage and clarification gateway | M1-01, M1-03, M1-04, M1-05 | Actual model-assisted plan and criteria/specification digest recorded; missing or ambiguous behavior pauses; authenticated answers create revisions; unknown/high risk cannot execute; input text cannot grant capabilities |
| M1-07 | Audit events, cancellation and command authorization | M1-03, M1-06 | Authorized expected-sequence commands; idempotent disposition; finite wait/retry budgets; cancellation survives restarts; logs omit credentials; state projection can be rebuilt |
| M1-08 | Evaluation qualification seed and development/validation split | M0-01, M1-05 | Initial eligible corpus and oracle qualified under evaluation protocol; historical answers withheld; dev/validation/held-out identities recorded; simple runner records all attempts and spend |

Gate: real authenticated intake becomes one recoverable revision-bound plan; clarification and denial work without code execution. Evaluation curation and the development harness are underway. No signing secret or control-plane token enters model context.

## M2 — Safe isolated build

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M2-01 | Sandbox threat model spike and selected execution profile | M1-07 | ADR-003 controls exercised on chosen Linux host; resource, filesystem, process, egress and credential probes pass; Docker availability and host prerequisites documented before execution is enabled |
| M2-02 | Pinned checkout, dependency preparation and baseline validator | M2-01 | Exact base/image/dependencies recorded; installation separated from offline execution; only configured commands run; baseline failures pause with actual evidence |
| M2-03 | Builder role context and tool broker | M1-05, M1-07, M2-01 | Extend selected provider adapter with builder tools; schema/timeout/rate-limit/errors tested; tools enforce policy outside prompts; spend accounted; builder cannot expand capabilities |
| M2-04 | Bounded builder and patch collector | M2-02, M2-03 | Builder edits only permitted workspace; no publishing credentials; sensitive diffs stop; traversal/symlink/oversize artifact tests pass; candidate commit/digest reproduced |
| M2-05 | Independent candidate runner and execution receipts | M2-04 | Fresh environment runs approved checks; exit codes/timeouts/skips retained; candidate matches tested head; artifact digests checked by trusted collector; builder claims cannot create trusted results |

Gate: a real admitted Python change is built and validated with demonstrated controls. A container alone does not establish isolation. Failure/cancellation cleanup and no-credential tests are mandatory before a pilot.

## M3 — PR, independent review and human handoff

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M3-01 | GitHub App publishing broker and draft PR reconciliation | M2-05, M1-07 | Least-permission installation restricted to onboarded repository; branch/PR updates idempotent; ambiguous API outcome reconciled; head preconditions enforced; no merge capability exposed |
| M3-02 | Fresh-context independent reviewer and bounded correction loop | M2-05, M3-01 | Reviewer lacks builder write/publish privileges; sees criteria/diff/actual checks; blocking findings create bounded repairs; every changed candidate gets new validation/review |
| M3-03 | Evidence manifest, criterion matrix and readiness gate | M3-02 | Repository/base/head/specification/plan/policy bound; missing, forged, stale, skipped, failing and conflicting evidence denied; required manual checks remain visibly pending; artifact bytes verified |
| M3-04 | Human handoff, Linear status and external outcome observation | M3-03 | Only complete current evidence makes PR review-ready; authenticated human review/merge controls; changed head invalidates readiness; actual merge/close observed separately; no deployment success inference |
| M3-05 | Pre-pilot development and validation A/B runs | M1-08, M3-04 | Execute builder-only and independently reviewed configurations under the evaluation protocol; retain all task outcomes/costs; validation promotion thresholds checked before any pilot; held-out campaign remains untouched |

Gate: a real Linear ticket reaches one GitHub PR with independent evidence and human merge. Under ADR-006, independent review and local acceptance precede publication. The PR stays draft for human review; `HUMAN_REVIEW` requires the complete current gate, including required GitHub checks. Green tests or model approval alone never establish delivery.

## M4 — Reliability and pilot acceptance

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M4-01 | End-to-end crash, retry, cancellation and provider fault suite | M3-04 | Exercise product P-04/P-05/P-07/P-08/P-12 with real storage/orchestration and controlled provider faults; no duplicate effect after lost response; finite cleanup and spend |
| M4-02 | Adversarial control and stale-evidence acceptance suite | M3-04 | Exercise P-03/P-06/P-09/P-11, repository prompt injection, secret access, malicious dependency/tests and revision races; unresolved control bypass blocks release |
| M4-03 | Operator runbook, diagnostics, retention and recovery | M4-01, M4-02 | Correlated redacted traces; backup/restore and projection recovery demonstrated; deletion/retention documented; kill switch and credential rotation rehearsed |
| M4-04 | Repeatable real integration demos and limited pilot | M4-03, M3-05 | All applicable P-01 through P-12 scenarios and evaluation validation promotion thresholds pass; run manifests retained; human operator signs off on documented limits; pilot stays within onboarded low-risk Python scope |

Gate: MVP acceptance is evidenced, including failures and recovery. This is a single-tenant pilot, not an enterprise production-readiness claim.

## M5 — Regression scope and published evaluation

| ID | Deliverable | Dependencies | Acceptance and evidence |
| --- | --- | --- | --- |
| M5-01 | Final frozen campaign corpus, oracle and provenance | M1-08, M4-04 | Extend qualified corpus to at least 30 eligible historical tasks under evaluation protocol; rights/provenance recorded; answers withheld; exclusions and splits frozen before reported runs; preserve prior validation/held-out separation |
| M5-02 | Full-suite baseline and bounded Python impact analysis | M2-05, M4-04 | File/import/test mapping with confidence and conservative fallback; compare against full-suite outcomes; unrelated behavior and changed tests remain visible; no unsupported no-regression claim |
| M5-03 | Reproducible benchmark runner and configuration comparisons | M5-01, M5-02 | Builder-only and independent-review configurations tested under comparable budgets; task-level outcomes, retries, costs, wall time and agent qualification/scoring provenance retained; actual human intervention recorded only if observed, human benefit otherwise unmeasured; failures included |
| M5-04 | Portfolio report and replayable demonstration package | M5-03 | Manifest and instructions reproduce measurements; uncertainty/limitations reported; no invented numbers; held-out answers excluded from public agent context; actual outcomes distinguished from future scope |

Gate: publish only measurements produced by the frozen protocol. Evaluation can reject the thesis or show that added review/impact complexity is not worthwhile.

## M6 — Later options, not MVP commitments

| ID | Option | Prerequisite decision and acceptance |
| --- | --- | --- |
| M6-01 | Additional trackers and languages | M5 report plus demonstrated demand; preserve provider-neutral domain; add contract and recovery suites |
| M6-02 | Data/AI/analytics worker profiles | Explicit scoped product need; separate execution/evidence/security design and measurable evaluation |
| M6-03 | Rich UI, retrieval or knowledge graph | Measured bottleneck and comparison against simpler solution; avoid increasing permissions/context without benefit |
| M6-04 | Multi-tenant hosting or upstream OS integration | New threat model, isolation/identity/cost design and ADRs before implementation |
| M6-05 | Release automation | Separate authorization and safety design; human-only MVP merge remains unchanged unless explicitly superseded by a future approved decision |
