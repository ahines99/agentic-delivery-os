# ADR-004: Conservative context and protected historical evaluation

- Status: Accepted
- Date: 2026-09-27
- Scope: Python MVP and portfolio evaluation

## Context

The original handoff proposed embeddings and a broad impact graph spanning code, APIs, data contracts, and services. The MVP covers one Python repository per run; it does not yet have evidence that semantic retrieval or graph infrastructure improves results. Public coding benchmarks also carry contamination and scoring-validity risks. A passing test suite is evidence about observed behavior, not a proof of complete correctness.

## Decision

Build a revision-bound, conservative context index from approved repository documentation, lexical search, Python AST symbols/imports, and measured per-test coverage. Store explicit relationships with provenance and unresolved cases. Do not claim a sound call graph or infer unseen runtime behavior. Rank tests for early feedback, but retain the full approved regression suite before review readiness. No embeddings, pgvector dependency, or graph database in the initial MVP.

Use the [evaluation methodology](../evaluation-methodology.md) as the normative protocol: target 36 real historical tickets, minimum 30; grouped development/validation/sealed-test splits; immutable bases; qualified acceptance/regression tests; protected human patches and hidden tests; fixed budgets; paired builder/reviewer/context arms; task-level provenance and complete failure accounting. Evaluation runs have the same execution boundary as live runs and no write/merge credentials. Builder-visible context must never include historical answers or protected evaluator artifacts.

Adopt more complex retrieval only after a preregistered development/validation experiment meets the methodology's benefit threshold without observed correctness/safety loss, followed by a new sealed evaluation. A small benchmark can guide implementation choices but cannot establish enterprise readiness or causal productivity savings.

## Consequences

The initial index is cheap to inspect and rebuild. Its uncertainty is explicit, and full-suite validation limits harm from missed edges. Cross-language, dynamic, and cross-service impacts remain unsupported. Qualification and protected scoring require real engineering and human effort before any portfolio performance claim. Independent review is a separation-of-duties requirement even if its measured effect is inconclusive.

## Alternatives

- Embeddings/pgvector from day one: deferred until there is measured benefit relative to simpler context and an accepted storage/privacy requirement.
- General call graph or graph database: deferred; dynamic Python cannot be comprehensively resolved by an AST import extractor.
- Public benchmark leaderboard as the release gate: rejected because task validity, overlap, and harness budgets differ from this product's operating conditions.
- Builder tests as the sole oracle: rejected because the builder can miss requirements or modify its own evidence.

Research basis: [evaluation review](../research/04-evaluation-review.md), primary sources accessed 2026-09-27.
