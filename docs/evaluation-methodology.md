# Evaluation methodology

Status: accepted protocol, revised 2026-09-28 under [ADR-007](adr/ADR-007-automated-benchmark-qualification.md). Partial manifest/scoring/curation tooling and a 36-candidate metadata catalog exist; no task is yet qualified and no historical campaign has run. This is the full protocol, not a claim that partial tooling implements it. This protocol owns evaluation choices; [the security model](security-model.md) owns execution controls.

Current consumer contract: historical export, scoring and campaign freeze require
`independent-agents-v2` evidence and a concrete in-process current qualification
authority with an action-specific grant. V1 records remain historical inspection
only. Candidate scoring also requires a separately metered execution account;
qualification alone grants no spending authority. Synthetic-purpose records cannot
authorize historical consumers. These implemented gates do not constitute a
qualified corpus, a completed historical campaign or measured human benefit.

## Questions and scope

Measure whether a bounded Python ticket produces a correct, reviewable candidate within budget; whether independent review catches defects; and whether conservative repository context helps. Do not treat a PR, passing builder tests, or a model's approval as success. Every MVP merge remains human.

Use curated historical tasks as the primary project evaluation. SWE-bench provides a useful patch-and-test pattern, but public benchmark familiarity and imperfect tests limit conclusions. Current primary-source audits also warn against substituting another public leaderboard for task validation. Our dataset is not inherently contamination-free. OpenAI's [Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) identifies flawed tests and contamination; its later [coding-evaluation audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) retracts its earlier Pro recommendation (checked 2026-09-28). The 36 staged public candidates therefore remain diagnostic inputs, not an assumed-valid ability benchmark. Neither switching datasets nor two agent votes establishes validity; every task still needs executed oracle qualification and independent semantic review. Prefer authorized recent alternatives if candidates fail, without relaxing eligibility or the corpus minimum. No frontier-ability or productivity claim follows from this catalog. See [research and sources](research/04-evaluation-review.md).

## Dataset and frozen splits

Target **36 real historical tickets**, with a release minimum of **30**. Freeze three equal splits (12/12/12 for 36; at least 10/10/10 for 30): development, validation, and sealed test. Additional tickets are assigned before any scored run. Collect at least three authorized Python repositories. Keep linked issues, overlapping fixes, backports, duplicate reports, and closely related task families in one split. Reserve at least one repository for the sealed test split; disclose the resulting repository distribution and difficulty differences. This evaluates transfer but makes small-sample comparisons less precise.

Admit only Tier 0/1, single-repository tasks with an immutable pre-fix commit, a reproducible supported environment, clear requirements available before the fix, an accepted human solution, and meaningful acceptance/regression checks. The project runtime is Python 3.12; an evaluated historical repository may use a separately pinned supported Python version. Do not silently modernize the task to make it runnable. Exclude tasks requiring secrets, live private services, unsafe privileges, paid data, or unsupported runtimes before freezing; retain reasons and counts.

Development supports prompt/tool/model changes. Validation selects one frozen configuration per arm and checks operational feasibility. Sealed test is opened once for the release comparison; reading its failures makes it development data for future releases. A new release needs a new sealed set. Historical replay is not a prospective production trial.

Two independent agent passes check each task's specification, risk, rights evidence and scoring relevance before admission. This replaces the earlier requirement for two human curators at the user's explicit request for a hands-off, fully agentic benchmark workflow; it does not authorize agent merges, bypass plan approval, or replace the human pilot signoff. Agent identities are recorded as agents, never as fictitious maintainers. The accepted historical human patch is an existence proof, not the only allowed implementation. Reject tests that demand undocumented names or behavior. For behavior changes require at least one meaningful fail-to-pass test; documentation-only tasks require a frozen calibrated automated rubric and a distinct reported stratum. At least 24 of the 30 minimum tickets must have executable behavioral acceptance.

Each pass uses a distinct invocation/context, sees the same frozen task evidence, and cannot see the other pass's verdict or private reasoning. Record model/provider/configuration and input/output provenance; differing model families are preferred where authorized, but separate contexts alone do not establish statistical independence. A fresh third agent adjudicates disagreements against the frozen criteria after both original records are sealed. Preserve all three findings and evidence references. Adjudication cannot overrule failed deterministic checks, absent usage authorization, unresolved risk, or missing provenance: the task remains UNRESOLVED/excluded with a reason until qualifying evidence exists. A timeout, model failure or uncertainty is not an affirmative vote. The controller checks contracts and records decisions; a model cannot directly mark a task admitted.

## Manifest contract

The normative campaign manifest is UTF-8 JSONL, one strict validated object per task. Unknown fields, duplicate IDs, mutable refs, invalid digests, empty required test sets, and unapproved paths are rejected. Publish the schema and nonsensitive task metadata with the evaluation implementation. The following is the normative field contract, not a populated dataset:

| Field | Type and constraint |
| --- | --- |
| `schema_version`, `dataset_version`, `task_id` | Nonempty strings; schema version starts at `1`; task ID unique within dataset |
| `split`, `family_id`, `stratum` | Split is `development`, `validation`, or `test`; family identifies related tasks; stratum is `behavior`, `tests`, or `documentation` |
| `repository_id`, `repository_url`, `license_id`, `usage_authorization_ref` | Stable provider ID; allowlisted HTTPS origin; license and authorization provenance |
| `base_commit`, `base_tree_digest`, `snapshot_ref` | Full immutable Git object ID plus SHA-256 of exported tree/archive; content-addressed read-only snapshot |
| `issue_id`, `issue_created_at`, `issue_snapshot_at`, `issue_text_ref`, `issue_text_sha256` | Original timestamped problem statement, frozen before the solution; UTC timestamps; no solution comments |
| `acceptance_criteria`, `risk_tier`, `selection_reason` | Nonempty list of `{id, text, verification_kind}`; risk `0` or `1`; documented selection justification |
| `environment` | `{image_digest, architecture, os, python_version, dependency_lock_sha256, harness_commit, command_profile_id, command_profile_sha256}`; no floating image tags |
| `scoring` | `{oracle_ref, oracle_sha256, fail_to_pass_ids, pass_to_pass_ids, expected_test_count, rubric_ref, rubric_sha256}`; oracle and rubric evaluator-only; rubric fields nullable for executable tasks |
| `reference_solution` | `{accepted_commit, patch_ref, patch_sha256}`; evaluator-only, never serialized into agent context |
| `baseline` | `{validation_artifact_ref, validation_artifact_sha256, repetitions, expected_failures}`; three successful qualification repetitions required |
| `limits` | `{wall_seconds, command_seconds, input_tokens, output_tokens, model_usd, infrastructure_usd, repair_rounds, transport_retries}`; finite positive limits, repair/retry counts may be zero |
| `curation` | `{qualification_record_ref, qualification_record_sha256, contamination_notes, related_task_ids, exclusions_considered}`; referenced record binds `schema_version`, `qualification_mode=agent`, `task_id`, `task_manifest_digest`, `qualification_input_artifact`, two `review_records` artifact digests and optional `adjudication_ref`; deterministic evidence and distinct executed contexts required |
| `manifest_sha256` | SHA-256 of canonical JSON excluding this field; canonicalization version fixed in dataset metadata |

Store an evaluator-only master manifest outside repositories visible to workers. Derive a minimal agent input containing the frozen issue/criteria, repository snapshot, permitted commands and public budget; it contains **no** oracle references, test IDs from withheld tests, accepted commit, reference patch, or curation answers. A published redacted manifest is separate from both. Even an evaluator-only file committed in the same checkout can leak through tooling; `.gitignore` alone is not access control.

Dataset metadata binds ordered task IDs, split assignment, sampling seed, criteria version, manifest digests, scoring code commit, and protocol version. Each result binds that dataset digest to run ID, arm, attempt, seed, repository/base/head, candidate patch digest, policy digest, prompt/tool configuration digests, requested and returned model identifiers, decoding settings, image/tool versions, cost rate-card date, timestamps, execution reports, agent qualification/scoring decisions, any actual human decisions, and exclusion decisions. Provider aliases may change; if a stable model snapshot is unavailable disclose the reproducibility limit and run arms in interleaved blocks.

## Qualification, leakage, and scoring isolation

1. An evaluator controller reconstructs the pre-fix environment in a protected workspace. In three clean repetitions require stable baseline regressions and the intended nonempty fail-to-pass acceptance failures; then apply the accepted historical reference patch to a separate clean copy and require acceptance plus regressions to pass in three clean repetitions. Record exact tree/image/dependency/command/test identities, collected phases, exit status, timestamps and content-addressed receipts for every repetition. An agent assertion cannot substitute for executed evidence. The two qualification agents independently assess specification/test relevance, rights/linkage, risk, environment and family grouping using the authorized frozen evidence. Their initial relevance review excludes the reference patch to limit anchoring; protected deterministic tooling applies that patch. Missing rights or unsupported privilege/runtime requirements fail admission rather than lowering eligibility.
2. Export only the exact pre-fix tree for the agent. Remove Git history/remotes, later release notes, solution branches, archived patches, oracle files, prior trajectories, hidden-test output, caches, and future-linked documents. Scan the exported archive against protected artifact names/digests; run an independent agent leakage review over a recorded sample in the protected qualification context, preserving its inspected-input digest and findings. Neither worker nor campaign builder/reviewer receives protected reference/oracle material. Pin dependency bundles from qualification.
3. Run the builder/reviewer under the same [sandbox policy](adr/ADR-003-sandbox-policy.md) as live tasks. No internet browsing or issue/PR retrieval during benchmark execution; no control-plane, repository-write, model-provider, or evaluator credentials in the sandbox. Agent model calls use the broker. Treat repository scripts, dependencies, tests, and logs as hostile.
4. Freeze the final candidate before evaluation. A separate credential-free scoring sandbox reconstructs the base plus candidate and mounts the trusted test bundle read-only. Run required test IDs from a trusted profile and assert their collection/counts; reject missing, renamed, skipped, xfailed, or replaced required tests. Protect test configuration and runner dependencies from candidate changes. A candidate cannot self-report authoritative results.
5. The grading controller remains outside that sandbox and authenticates result provenance. Candidate code executes alongside tests and can still attempt tampering; use external behavioral probes where possible and independently score every apparent success in two isolated evaluator-agent passes for harness manipulation, hardcoded answers and requirement gaps. Evaluator contexts are separate from builder/reviewer contexts and cannot feed protected outputs back into repairs. Resolve disagreements under the same third-agent/fail-closed rule as qualification. Hashes alone do not prove semantic correctness.
6. Do not expose withheld tests or their detailed outputs to any arm during repairs. Evaluate once after the candidate is final. Store protected oracle outputs separately from builder-visible logs. Full archives are released only after retiring a split and checking permissions; retain enough restricted artifacts to reproduce private results.

### Automated review evidence and calibration

A review record binds a unique invocation/context ID, stage (qualification roles `qualifier_a`, `qualifier_b`, `adjudicator`; scoring roles separately declared), task/manifest/candidate digests where applicable, reviewer type `agent`, provider, requested/returned model IDs, prompt/configuration/input/output digests, criterion-level findings with evidence references, verdict, timestamps and measured token/cost usage. Qualification outputs use `ADMIT`, `REJECT` or `UNRESOLVED` and criterion checks/evidence references; stage labels are not actor authentication. A nonempty reviewer name alone is not evidence. Store canonical record bytes and the underlying immutable artifacts outside worker-visible repositories; rehash and validate their reference chain before promotion. No private chain of thought is required. A third adjudication record cites both sealed original records and its own distinct invocation/context.

Freeze rubric version and anchors on development material only. Calibrate agents against deterministic known-pass/known-fail and deliberate tampering fixtures, record disagreements/false approvals, and require all mandatory safety/false-ready fixtures to pass before using the rubric for admission or reporting strict success. No validation or sealed-test result may tune the rubric. Executable acceptance/regression results are authoritative: no agent score can turn a failing, incomplete or tampered test result into success. For non-executable criteria, require agreement (or evidence-backed resolved adjudication) on the frozen rubric and report the automated stratum separately. If calibration cannot establish a reliable criterion, leave it unresolved rather than invent a label.

These are automated correctness/reviewability judgments with correlated-model and oracle limitations. They do not measure actual human review benefit, human effort saved or production correctness. `human_minutes` and human-benefit results must be unknown/not measured unless a person actually participated and the observation was recorded; agent elapsed time cannot be converted into fabricated human minutes. Any later real human study is a separately labeled extension, not a prerequisite for this agent-led benchmark.

Pretraining contamination cannot be ruled out by removing local files. Record repository/publication dates and suspected memorization. Prefer recent authorized tasks; prospective private tasks are a later validation cohort. Never claim that an older model cutoff proves no contamination.

## Paired comparison and budgets

Every primary arm receives the same tasks, snapshots, base tool permissions, model version, total resource ceilings, and mandatory full regression suite. Randomize and record task/arm execution order. An omitted primary task is not a success. Compare:

| Arm | Configuration | Question |
| --- | --- | --- |
| A | Builder with self-checks and ordinary file/keyword context | Baseline capability and error rate |
| B | A plus fresh independent review and bounded correction | Does review improve correctness or reduce false readiness within the same total budget? |
| C | B plus AST import relationships and measured test coverage context | Does bounded context improve outcomes or time to detect a failure? |

Start dataset curation and isolated model-selection development experiments in M1. M4 pilot qualification requires A/B development and validation results; C is introduced in M5 after the bounded index exists. M5 reruns advertised arms with a shared frozen configuration policy and opens the sealed test once. A/B pilot work must not inspect sealed tasks or depend on the later C implementation.

Run one primary attempt per task/arm. Before observing results select a stratified six-task stability subset and run two additional seeds per arm; report these separately, never replace the primary result with the best repeat. Seeds are provenance, not a guarantee of deterministic hosted inference. A 36-task, three-arm campaign has 108 primary and 36 additional attempts. Report equal-cap comparisons, actual spend, and tradeoffs; review consumes part of the cap rather than getting unreported extra compute.

Default v1 ceilings per attempt: **30 minutes active wall time**, **10 minutes per command** (bounded by remaining run time), **100,000 total input tokens**, **20,000 total output tokens**, **USD 5 model spend**, **USD 1 infrastructure spend**, **two repair rounds**, and **two transient transport retries per operation**. All calls, retries, reviewers, and repairs share totals. Reserve worst-case cost before issuing a call; stop if admission would exceed a limit or pricing is unknown. Preparation/qualification is separately metered. Human wait time does not consume active compute time but is recorded separately. Cancellation terminates active work within a 30-second grace period; a failure to stop is a safety failure.

The planned campaign ceiling is **USD 1,000 total measured model and infrastructure cost**, including qualification and repeats; this is a design cap, **not authorization to spend money now**. At the per-attempt maximum, 144 attempts cost at most USD 864, leaving USD 136 for qualification. If qualification or reserved costs cannot fit, stop before starting scored runs and preregister a smaller valid campaign or request a later budget decision. Never drop expensive failures after observing outcomes. Agent qualification, both scoring passes, adjudication, retries and calibration are metered within the campaign cap, including preparation costs. Any actually observed human intervention is recorded separately; absent participation is unmeasured human benefit, never an estimated saving. The user's automation preference does not authorize unlimited or previously unauthorized spend.

## Outcomes and denominators

All rates include integer numerators and denominators. Report each split/arm separately; the release headline uses sealed test only. The development/validation counts establish the 30+ historical-task coverage but are not an unbiased headline.

| Metric | Definition |
| --- | --- |
| Strict task success | Tasks meeting every frozen criterion, trusted acceptance/regression check, policy/evidence requirement, and frozen calibrated automated correctness rubric / all frozen tasks assigned to that arm |
| Functional acceptance | Tasks meeting frozen behavioral tests or documentation rubric / all assigned tasks; report strata separately |
| False-ready rate | Candidates declared review-ready by the system but failing independent deterministic final scoring or the frozen automated rubric / all system-declared review-ready candidates; zero denominator is `N/A`, not zero |
| Regression rate | Candidates with a failure in a previously stable pass-to-pass test / candidates with a completed trusted regression run; also report incomplete regression runs / all assigned tasks |
| Criterion coverage | Criteria with current valid passing evidence / all required criteria; distinguish manual, automated, pending, and not-applicable |
| Review effect | Paired B-minus-A and C-minus-B task outcomes, discordant pairs, defect catches, reviewer false alarms, review cost, and repair effort |
| Cost | Total model plus infrastructure cost / all assigned tasks; also total spend / successful tasks, `N/A` if none; include failed/retried work |
| Time and effort | Measured active wall time, time to first failing check, agent review/repair/qualification time and any actual human intervention separately; unobserved human effort/benefit is unmeasured, not zero or saved time; show task-level observations and medians, with timeout counts |
| Reliability | Completed without infrastructure fault / all assigned runs; report retry/recovery, duplicate side effects, cancellation failures, and orphan resources as counts |

Timeout, budget exhaustion, empty/non-applying patch, policy violation, invalid evidence, unjustified refusal, and model/provider error are unsuccessful in the strict denominator. Do not compute latency only from successes without labeling that selection. Record failures at their elapsed time and flag right-censoring at a timeout; avoid a precise p95 claim from a tiny sample.

A verified infrastructure incident may receive one fresh rerun **in addition to**, not in place of, the original record. It requires an immutable controller finding, supported by clean-baseline reproduction and independent agent checks, that the fault is unrelated to candidate changes; disagreement remains unresolved and cannot remove the original result. Missing dependencies introduced by a candidate, intentional resource exhaustion, ordinary budget timeouts, and ambiguous failures are not infrastructure exclusions. Publish strict original results and a separately labeled infrastructure-adjusted sensitivity result; list every changed denominator. If more than 5% of assigned runs have infrastructure incidents, fix the harness and start a newly versioned campaign before promotion.

Use task-level 95% Wilson intervals for binary rates and paired task bootstrap intervals for differences, fixed seed and method recorded. Repository/task clustering limits these intervals; small samples are descriptive evidence, not proof of broad superiority. Do not treat repeated seeds as independent tasks or compare to external leaderboard scores with different budgets/datasets.

## Operational fixtures and promotion gates

Historical success alone cannot validate control-plane safety. Maintain a separate suite for ambiguity, unsupported/high-risk work, malicious instructions, forged/stale evidence, hidden-test access, transport failure, crash recovery, duplicate events, resource exhaustion, and cancellation. It is excluded from historical functional-success denominators and reported scenario by scenario.

Targets below are release decisions chosen for this project, **not achieved results or industry standards**:

- Before connected execution: all applicable security and lifecycle acceptance scenarios pass, baseline qualification is repeatable, and no known critical control bypass remains.
- Before a supervised pilot: all mandatory control fixtures pass; validation strict success is at least 60%; false-ready count is zero; evidence completeness is 100%; infrastructure incidents are at most 5%; all runs respect configured ceilings or explicitly fail closed. A zero observed false-ready count does not establish zero underlying risk.
- Before the portfolio release: at least 30 qualified historical tickets have primary results for every advertised arm; sealed-test strict success is at least 60%, zero observed false-ready candidates, and the same operational gates pass. Publish failures, intervals, costs, censored timings, and limitations even when targets are missed. Missing targets means experimental status continues; it does not justify changing the frozen denominator.
- Keep independent review as a governance requirement even if the small sample finds no accuracy improvement. Claim an improvement only when the paired evidence supports it. Introduce embeddings or a more complex graph only after a development/validation experiment shows at least a 5-percentage-point strict-success increase or at least a 15% median cost/time reduction with no observed loss of correctness or safety; then test the frozen choice on a fresh sealed set. These are decision thresholds, not statistical significance guarantees.

## Context and impact analysis

Start with allowlisted tree/docs, lexical search, Python AST `Import`/`ImportFrom` edges, symbols, and per-test coverage contexts. Resolve relative imports against pinned package roots and store each edge with file/line, revision, extractor version, and known/unknown status. Traverse reverse module imports to suggest impacted modules/tests; use measured coverage to rank relevant existing tests. Never execute imports to construct the static graph.

Dynamic imports, plugins, namespace packages, reflection, generated code, non-Python assets, runtime dispatch, absent coverage, and changed public/configuration/dependency interfaces make the graph incomplete. Parse failures and unresolved edges are visible uncertainty. Fall back to the full approved suite on uncertainty; the MVP runs that suite before readiness in every case. Context ranking can improve early feedback, but it cannot prove unselected tests are safe or establish absence of regressions. Coverage maps bind to exact revisions/toolchains and expire on relevant changes. Embeddings and a graph database are deferred by [ADR-004](adr/ADR-004-context-and-evaluation.md).

## Release artifact checklist

Publish a dated report with protocol/configuration digests, permitted manifests, environment reconstruction instructions, selection/exclusion ledger, task-level outcomes, paired comparisons, provenance, cost accounting, labeled automated rubric/calibration/adjudication results, actual human observations only if obtained, and limitations. Keep secret or licensed artifacts in protected storage with an access procedure. A reviewer must be able to distinguish a test failure, a harness failure, an unrun task, and a withheld private artifact. No benchmark numbers may appear in README or portfolio claims until backed by such a run.
