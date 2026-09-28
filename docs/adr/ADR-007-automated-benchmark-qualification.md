# ADR-007: Agent-led benchmark qualification and scoring

Status: accepted user-directed protocol revision. Date: 2026-09-28.

## Context and scope

The original evaluation protocol required two actual human curators and human correctness
rubric decisions. In response to that requirement, the user explicitly said: "It would be best
to be hands off and fully agentic". This changes benchmark qualification and scoring to an
agent-led process. Requiring human reviewer names for those decisions would contradict the
updated preference. It does not turn unperformed reviews into completed evidence.

This decision does not authorize automatic product merges, waive authenticated plan approval,
replace the human pilot signoff, grant missing data rights, authorize new provider access, or
remove budget limits. GitHub App and Linear onboarding remain product-integration prerequisites.
The accepted historical human solution remains reference evidence, not a requirement that new
human reviewers perform qualification and not the only correct implementation.

## Decision

1. Execute two qualification passes in separate agent invocations and contexts against identical
   frozen authorized evidence. Neither sees the other's verdict. Record actual agent provenance:
   task/input/configuration/prompt/output digests, provider and requested/returned model identities,
   invocation/context IDs, criterion findings with evidence references, timestamps and measured usage.
   Different model families are preferred when available within authorization and budget; isolation
   alone does not prove statistical independence or eliminate correlated judgment.
2. A deterministic evaluator controller reconstructs immutable pre-fix environments. Require three
   clean stable baseline repetitions with meaningful expected acceptance failures and stable
   regressions, followed by three clean reference-solution repetitions passing acceptance and
   regressions. Retain actual collection/phase/exit and environment/snapshot receipts. Agent votes
   never replace these executions or override missing/failing evidence.
3. Seal both initial reviews. A distinct third invocation/context may resolve semantic disagreement
   using the frozen criteria and cited evidence. Retain both original findings and adjudication.
   Unresolved findings, missing rights, unsupported risk/runtime, failed checks and missing provenance
   remain blocked/excluded with explicit reasons; a majority vote cannot manufacture authorization.
4. Freeze a development-calibrated rubric before validation or sealed-test scoring. Calibrate on
   deterministic known-pass/known-fail and deliberate tampering fixtures; mandatory safety and
   false-ready fixtures must pass. Score final candidates with deterministic acceptance/regression
   execution and two separate evaluator-agent passes. Any unresolved rubric criterion prevents strict
   success; executable failures cannot be overturned by an agent's score. Report non-executable
   strata and automated rubric judgments separately.
5. Store canonical, immutable, machine-auditable records and their complete artifact reference chain
   outside campaign-worker repositories. Protected qualification/scoring contexts are separate from
   builder/reviewer contexts. Initial semantic relevance review excludes the reference patch;
   deterministic protected tooling applies it. No withheld answers or detailed oracle outputs feed
   back into repair. No fictitious human identities, minutes, savings or approvals are permitted.

The full [evaluation protocol](../evaluation-methodology.md) retains minimum 30/target 36 real
tasks, at least three repositories, task-family grouping, equal development/validation/sealed-test
splits, a held-out repository, at least 24 behavioral tasks, matched A/B/C budgets, stability repeats,
strict denominators, uncertainty, contamination controls and unchanged safety/false-ready thresholds.
Qualification, both scoring passes, adjudication and calibration consume measured campaign budget.
The USD 1,000 ceiling is a cap, not new spending authorization. If evidence cannot fit the budget,
stop or preregister a valid revised campaign before outcomes; do not discard costly failures.

## Validity and reporting limits

OpenAI's [Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)
identifies flawed tests and contamination. Its later
[coding-evaluation audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/)
withdraws the earlier recommendation to use Pro (checked 2026-09-28). The current 36 public metadata
candidates remain diagnostic candidates, not an assumed-valid benchmark of ability or productivity.
Each still requires individual oracle and semantic qualification; prefer authorized recent
alternatives when unsuitable, without relaxing task eligibility to make the catalog pass.

Independent agent contexts can share training contamination, mistakes and preferences, especially
within one provider/model family. Passing tests and agent agreement do not establish complete
semantic correctness or absence of harness manipulation. Report that limitation and all unresolved
cases. Automated reviewability/correctness scores must be labeled automated. Human review benefit,
hands-on effort and productivity savings remain unmeasured unless real people participate and actual
observations are recorded; agent elapsed time is not a substitute.

## Implementation and migration boundary

The metadata staging catalog contains zero qualified and zero scored tasks. Accepting this ADR
does not promote them. Replace legacy human-only worklist/schema requirements with explicit agent
provenance and fail-closed admission, preserving old historical records as their actual review type.
Reject fabricated or incomplete legacy reviewer-name lists as qualification evidence. Partial schema
and scoring tooling must identify which full protocol checks it actually enforces; contract-valid
input alone does not prove real execution. No hidden answers or paid model calls were accessed to
write this protocol revision.
