# ADR-002: Separate proposals, execution, verification, and human authority

- Status: Accepted for the implementation plan
- Date: 2026-09-27

## Context

The supplied blueprint correctly rejects builder self-approval but still proposes a merge agent and many agent personas before enforceable capability boundaries. Different prompts can share the same failure mode. A reviewer's confidence cannot authorize a privileged operation.

## Decision

Use three model contexts initially: requirements/planner, builder, and independent reviewer. Run policy admission, workflow transitions, evidence validation, and publication as deterministic services. Testing is executed by a separate runner against an immutable candidate; the reviewer assesses adequacy but cannot fabricate runner output. Additional model personas are deferred until evaluation demonstrates a measurable benefit.

| Actor | Allowed | Forbidden |
| --- | --- | --- |
| Planner | Read bounded context; propose criteria and plan | Execute repository code; grant permissions |
| Builder | Edit candidate workspace; request sandbox checks; submit patch | Read broker secrets; approve work; alter policy; publish directly |
| Test runner | Execute admitted test profile; emit provenance-bound results | Change policy; approve or publish work |
| Reviewer | Read immutable requirements/diff/evidence; report findings | Mutate candidate; act as human; approve its own identity |
| Publisher broker | Fetch configured repository; publish validated candidate branch/PR/evidence | Run target hooks/scripts; merge; deploy; bypass protected branches |
| Human | Clarify requirements; approve plans/reviews; merge in GitHub | Delegate authority implicitly through untrusted ticket text |

No agent merges at any risk tier. The source-control agent interface has no merge method. A future proposal to automate merges requires a superseding ADR, threat-model review, and separate user decision; it is outside this plan.

Fresh review context includes the original requirements and evidence, not hidden builder reasoning. Approval records bind repository, PR, exact head/base, plan where relevant, criteria, policy, evidence, authenticated actor, and expiry. Changed inputs invalidate approval. Tier 0/1 are the only MVP execution tiers; Tier 2/3 pause before tools. Reclassify based on the actual diff, including seemingly harmless files that affect CI, policy, dependencies, or test execution.

## Consequences

The platform can honestly claim independent workflow roles, not statistically independent intelligence. Same-model correlated errors remain an evaluation question. Model critiques are advisory; deterministic provenance checks, sandbox boundaries, provider protections, and human review remain necessary.

A publisher with GitHub contents permissions needs provider branch protections and no bypass privileges, because its token permissions alone do not implement a branch-prefix restriction. Enable stale-review dismissal and required trusted checks in the connected repository. [GitHub ruleset documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) (accessed 2026-09-27).

## Verification

Release tests must show that builder identity cannot record authoritative approval/evidence; reviewer cannot edit the candidate; stale input tuples lose readiness; and no tool invocation, retry, or direct ref operation allows an agent merge. See [security-model.md](../security-model.md).
