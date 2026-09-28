# Product review and research

Reviewed: 2026-09-27. Input: the supplied *Agentic Delivery OS Repository Handoff and Implementation Blueprint*. This document records research and product judgments, not implemented capabilities or benchmark results.

## Decision

Keep the central thesis: turn a bounded software ticket into a reviewable pull request with trustworthy evidence and human control. The original proposal combines a useful first product with several research programs. Commit the MVP to one Python repository per run, Linear intake, GitHub publication, one model provider, and low-risk software work. Deliver a runnable local foundation now; label integration and agent execution work as future implementation.

## Primary-source findings

| Finding supported by the source | Product judgment for this project |
|---|---|
| Anthropic distinguishes predefined workflows from model-directed agents and recommends starting with simple compositions, adding complexity when justified. [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), published 2024-12-19; accessed 2026-09-27. | Use three model contexts initially: requirements/planning, builder, independent reviewer. Implement policy, state transitions, command authorization, artifact validation, and evidence admission in ordinary code. Ten named roles need not mean ten independent model loops. |
| Anthropic recommends prototyping a small set of tools against realistic evaluations, improving their definitions and behavior using results. [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents), published 2025-09-11; accessed 2026-09-27. | Start with repository read/search, bounded patch application, and sandboxed validation. Add a tool only when an evaluation failure demonstrates a need. Budget tool results and retain structured provenance. |
| SWE-bench evaluates repository issue resolution; its Verified subset contains 500 human-filtered instances. [Official SWE-bench leaderboard](https://www.swebench.com/), accessed 2026-09-27. | Use compatible task/repository snapshots as one reference, but do not equate a benchmark pass with useful delivery. Our own evaluation must include clarification, replay, stale evidence, policy violations, and reviewer effort. Public historical solutions may have entered model training; disclose that limit. |
| METR's time-horizon measure describes human task difficulty at a specified model success probability, rather than the actual time the agent spends. [Task-completion time horizons](https://metr.org/time-horizons/), accessed 2026-09-27. | Bound ticket size and stratify evaluations by task complexity. Do not extrapolate a model leaderboard into promised autonomous project duration. Record human effort estimates separately from observed agent duration. |
| METR's study of 16 experienced contributors doing 246 tasks with early-2025 tools found a 19% increase in completion time in that particular setting. The authors explicitly limit generalization to other tools and settings. [Original study](https://metr.org/Early_2025_AI_Experienced_OS_Devs_Study-paper.pdf), published 2025-07-10; accessed 2026-09-27. | Measure review, repair, prompting, and intervention time. Do not use PR count, lines written, or subjective speedup as productivity proof. This historical result is a measurement lesson, not a claim about September 2026 models. |
| GitHub directs people to thoroughly review agent-created PRs and documents a human approval step for running their workflows by default. [Review output from Copilot](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/review-copilot-output), accessed 2026-09-27. | Treat a PR as an untrusted contribution. Separate builder execution, validation, and human merge authority. Human-only merge is this project's deliberate policy, not a claim that every current competitor has that restriction. |

## Changes to the supplied blueprint

1. **Move controls forward.** Policy, credential separation, execution limits, redaction, and evaluation fixtures precede the first execution of repository code. They cannot wait until the sixth milestone.
2. **Separate evidence from assertions.** A model may propose a requirement-to-test mapping. A trusted validator records the command, environment, result, repository SHA, and artifact digest. A generated test that passes is useful evidence but does not independently establish that the requirement is correct.
3. **Separate review readiness from delivery.** The agent produces a review-ready PR. A human merges it. Deployment completion is a separately observed outcome and is outside the initial execution scope.
4. **Reduce initial role count.** Preserve separation of duties with three contexts and an independent verification runner. Split out more model roles only through measured ablations.
5. **Bound repository intelligence.** Start with file search, Python syntax/import relationships, and repository-declared validation commands. Run the full affordable suite. Defer cross-service call graphs, embeddings, and data lineage until basic retrieval has measured limitations.
6. **Make the first demo honest.** A local JSON intake/policy demo demonstrates contracts and control decisions. It is not a functioning coding agent or the Linear-to-PR MVP.
7. **Treat independent review as a hypothesis.** Fresh context prevents shared conversation contamination; it does not guarantee statistically independent errors, particularly with the same model. Compare builder-only and builder-plus-review under equal declared budgets.
8. **Defer breadth.** Jira, GitHub Issues ingestion, extra programming languages, AI/data/analyst workers, dashboards, automatic deployment, and value-creation integrations follow evidence of benefit from the first workflow.
9. **Avoid premature commercial claims.** A single-tenant portfolio pilot is the target. Ordinary Docker isolation on an owner's machine is not a sufficient claim of hostile multi-tenant isolation.
10. **Retain naming stability.** Product: Agentic Delivery OS. Keep the existing repository directory `agentic-delivery-engineer`; renaming is unnecessary for delivery.

## Investment sequence

The priority is a short, observable lifecycle, then a reliable lifecycle, then measured improvement. Build contracts and a local demo first; add persistence and authenticated intake; add execution controls and a real builder; add independent review/evidence publication; harden replay and failure recovery; publish evaluations before expanding work types. The [product specification](../product-spec.md) defines acceptance and exclusions; the project roadmap owns milestone ordering and task estimates.

The first model/provider choice is made against the development evaluation set during integration work. The repository should not embed speculative current model IDs or claim neutrality while depending on unimplemented alternative providers.
