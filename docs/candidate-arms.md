# Shared candidate iteration engine

`agents/candidate_engine.py` extracts the production baseline, build, self-check,
criterion-check and bounded correction loop. It receives worker-safe task, plan,
base files, command profiles and protection settings plus caller-owned typed build,
review, verification and authorization callbacks. It accepts no historical manifest,
oracle, reference files, artifact store, workflow store or credentials.

Builder-only mode requires `review=None` and returns `BUILD_VERIFIED` after successful
self-checks. It never fabricates an independent review or product readiness. Independent
mode requires a reviewer callback and returns `REVIEW_APPROVED` only under the existing
criterion/verdict rules with exactly one verdict per criterion. Duplicate or conflicting
criterion verdicts cannot produce approval. Both use the same builder context and validation path; their
caller uses the existing unchanged builder prompt. Validation failures consume the
same configured correction ceiling; review and repairs share the caller's total budget.

Results contain immutable serialized evidence and candidate bytes with the candidate
digest. Normal correction exhaustion retains the final changed candidate for a later
one-way scoring controller, with status `FAILED`. A failed baseline has no candidate.
Policy, malformed output and callback errors still raise; callers retain operation
receipts/checkpoints and must not infer an authorized retry from an exception.

The product wrapper always chooses independent review and constructs its existing
`LOCAL_REVIEW_READY` manifest only from `REVIEW_APPROVED`. Its public failure shape,
prompts, operation IDs and manifest checks are preserved. Original-test protection
uses the scorer's conservative rule: any `test`/`tests` path component, a `test_`
filename prefix, or an `_test.py` suffix; modification and deletion both fail.
No product API exposes builder-only mode and no human approval/merge rule changes.

The engine does not authorize effects, meter infrastructure, create accounts, cancel
an active callback, or enforce a campaign schedule. The caller must enforce current
authority, reserve all effects, bound active work/deadlines and cleanup, and keep
protected evaluation inputs out of callbacks and worker-visible storage. Future
campaign allocation, equal-cap accounting, sealed phases and independent semantic
scoring remain separate work. Neither success status is a benchmark success claim.

Owned callback tests cover A/B contexts, zero review calls for A, self-check and review
repairs, final failed candidate retention, baseline refusal, protected edits, revocation
and invalid modes/budgets. Two optional actual-Docker tests use the production model
adapter and usage ledger with controlled HTTP responses, checking collector bindings
and exact model-call roles. Existing actual-Docker product correction/exhaustion and
manifest suites exercise wrapper compatibility. These are scripted control tests, not
live model ability or historical campaign evidence.

Recorded isolated check: **94 passed in 52.08 seconds** across the new engine tests,
product pipeline/authorization tests, actual correction/exhaustion tests, manifest
validation and baseline-failure tests. Both flat and src layouts used existing image
`sha256:136340a9d0e974bb74700fd4caa874f4fefd757b6683e6347e83bf8228041138`.
Ruff check/format passed for 247 files and mypy for 82 source files. This is scoped
regression evidence, not a new complete-suite or hosted-CI result.

The review follow-up added twelve original-test modification/deletion cases across
A/B and three duplicate/conflicting review-verdict cases. Relevant unit/manifest/
authorization regression checks passed **101 tests in 4.83 seconds**; actual Docker
A/B and product correction/exhaustion checks passed **4 tests in 30.64 seconds**.
Ruff and mypy remained clean. Earlier scoped counts above describe their own runs.
