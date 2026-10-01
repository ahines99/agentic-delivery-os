# Review 04: Evaluation and repository context

Reviewed 2026-09-27. This independent review covers the historical handoff, accepted product/security contracts, benchmark design, and impact-analysis scope. Recommendations are incorporated into [the protocol](../evaluation-methodology.md) and [ADR-004](../adr/ADR-004-context-and-evaluation.md). There are no project benchmark results yet.

## Findings

**Retain the historical-ticket benchmark, but make its oracle and provenance explicit.** SWE-bench's harness applies candidate patches to controlled repository environments and records distinct graded/error outcomes. Its documentation warns that reusing a run/instance ID may reuse cached results despite a changed patch. Bind every evaluation to the candidate digest and fresh run identity; preserve failures and cache provenance. [Official evaluation guide](https://www.swebench.com/SWE-bench/guides/evaluation/).

**Acceptance and regression are separate obligations.** SWE-bench grading distinguishes fail-to-pass resolution from pass-to-pass maintenance. Adopt that distinction while rejecting missing or empty required test sets rather than granting a vacuous success. Add requirement-level human review because a test pass cannot prove test adequacy. [Official harness API](https://www.swebench.com/SWE-bench/api/harness/).

**A familiar benchmark is not a clean scientific control.** OpenAI's 2026 audit reports specification/test problems and contamination evidence in SWE-bench Verified. Its later SWE-bench Pro audit reports further validity problems. These are first-party audit findings, not proof that every task is unusable or that our local sample is clean. They support curating and qualifying individual tasks, documenting ambiguity, withholding answers, and declining unsupported generalization. Do not mechanically replace one public benchmark with another or advertise leaderboard parity. [Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), [coding evaluation audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/).

**Start with observables rather than a universal impact graph.** Python's AST exposes imports and relative-import levels; it does not supply whole-program runtime dependency resolution. Coverage contexts associate executed code with tests but only for observed executions. Combine those bounded signals with lexical retrieval, versioned provenance, and visible unknowns. Keep full-suite validation; defer embeddings, inferred cross-service edges, and specialized graph storage until a paired evaluation demonstrates value. [Python AST documentation](https://docs.python.org/3.12/library/ast.html), [Python import system](https://docs.python.org/3.12/reference/import.html), [Coverage.py contexts](https://coverage.readthedocs.io/en/7.12.0/contexts.html).

## Accepted project choices

| Handoff proposal | Decision and reason |
| --- | --- |
| At least 30 historical tickets | Retain; target 36 with minimum 10 tasks in each of development, validation, and sealed test, grouped against related-task leakage |
| Compare single and multiple agents | Retain as equal-cap paired arms, with strict denominators and all retries/costs included |
| Compare impact graph/retrieval | Limit first comparison to AST imports plus coverage; measure early detection and correctness while keeping full regressions |
| Known accepted human implementation | Use for qualification only; keep patch, commit references, hidden tests, and later discussion outside every agent-visible workspace |
| Broad success metrics | Specify strict task success, false-ready rate, regressions, cost per assigned/successful task, human effort, timeout censoring, and infrastructure sensitivity results |
| Portfolio outcome claims | Publish only after reproducible runs with task selection, immutable commits, config/model/image identifiers, raw outcomes, and limitations |

The protocol fixes the dataset contract, qualification procedure, resource ceilings, outcome denominator rules, paired comparisons, and promotion targets. Those thresholds are deliberate product choices rather than values established by these sources. A minimum-sized sealed set is small; zero observed safety errors does not demonstrate zero risk. Human review and controlled execution remain mandatory regardless of average benchmark scores.

## Primary sources

All links accessed **2026-09-27**. Pin documentation/tool versions in actual run metadata; these web pages can change.

1. [SWE-bench evaluation guide](https://www.swebench.com/SWE-bench/guides/evaluation/) — patch evaluation, result accounting, and cache behavior.
2. [SWE-bench harness API](https://www.swebench.com/SWE-bench/api/harness/) — fail-to-pass/pass-to-pass grading and outcome states.
3. [OpenAI: Why SWE-bench Verified no longer measures frontier coding capabilities](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) — first-party audit of specification, test validity, and contamination concerns.
4. [OpenAI: Separating signal from noise in coding evaluations](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) — later audit cautions about SWE-bench Pro task validity.
5. [Python 3.12 AST documentation](https://docs.python.org/3.12/library/ast.html) — import and syntax-tree primitives.
6. [Python 3.12 import system](https://docs.python.org/3.12/reference/import.html) — runtime import behavior and resolution complexity.
7. [Coverage.py 7.12 measurement contexts](https://coverage.readthedocs.io/en/7.12.0/contexts.html) — recording coverage associated with test execution contexts.
