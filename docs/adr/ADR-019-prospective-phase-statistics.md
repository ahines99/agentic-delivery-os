# ADR-019: Bind phase statistics to prospective reporting policy

Status: accepted and implemented prospectively, 2026-09-29. No historical campaign result exists.

## Decision

New reporting-policy freezes include `current-ab-task-bootstrap-v1`, the campaign's original
seed, 2,000 paired task resamples, 95% intervals, and linear percentile interpolation at
position `(n-1)*p`. These are descriptive statistics for the existing A/B protocol. The method
is pinned with the readiness policy before phase opening and canonical account creation.
Previously pinned policies without statistics remain inspectable and retain no statistics;
inspection or repeated freezing cannot add the method after observing outcomes.

Report development, validation and sealed test separately. Primary strict-success rates and
paired differences retain every frozen assigned task; an unavailable or unresolved result is
not a success, and remains explicitly unavailable or unresolved rather than a fabricated
scored FAIL. Only pairs with two resolved verdicts enter verified success-discordance counts.
These counts do not themselves prove reviewer defect catches or human benefit.

Use task-level Wilson intervals for primary binary rates. Stability attempts are described
separately without treating repeated seeds as independent tasks or supplying task-level
intervals from repeat counts. Primary paired bootstraps share sampled task indices across
arms. Cost differences use only pairs with two validated completed attempts; report that
selection and undefined resamples. Repository/family dependence remains an explicit limitation.
When results are incomplete, intervals describe the recorded-success indicators with missing
assignments retained as non-successes. They do not model what those unobserved outcomes might
have been. Missing/unresolved counts remain attached, and incomplete comparisons cannot
support a superiority claim or replace the complete-evidence gate.

Expose actual acceptance/regression booleans from the current completed-scoring consumer.
That consumer verifies the exact original collection and complete setup/call/teardown evidence,
including legitimate failed assertions. Candidate failure before scoring has no completed
regression verdict. Its missing run remains in the incomplete-regression denominator.

Attempt timing uses the original allocation start and verified final completion checkpoint,
including adjudication when present. This is elapsed wall time among validated completed
attempts, not CPU time, a complete timeout distribution, or human review time. Missing timings,
timeout counts and human effort cannot become invented zero observations.

## Numeric checks and authority

For each primary arm and phase, assess the existing 60% strict-success target, zero confirmed
false-ready candidates and complete resolved final verdicts. A success threshold can pass
when its known numerator already reaches the target; it can fail when even all unresolved
assignments succeeding could not reach it. Otherwise it is incomplete. Missing readiness
or unresolved ready verdicts cannot pass the zero-false-ready check. Zero ready denominator
remains an N/A rate. Repeat success does not replace or promote the primary outcome.

These are individual numeric observations, not a choice of which arm may authorize a pilot.
The full protocol still requires criterion-level evidence completeness, verified infrastructure
incident classification, operational fixtures, complete program cost enforcement and human
pilot signoff. Missing gate consumers are explicitly unavailable. No phase opening, execution
authority or pilot permission follows from arithmetic or a serialized report.

The optional [requirement inventory](../campaign-criterion-inventory.md) now captures a
complete task-count sidecar under current qualification before policy/phase/allocation.
Its reference is pinned in the original reporting policy, preserving existing campaign
manifest and registration hashes. Statistics read that metadata without loading unstarted
protected task contexts. Older policies without the inventory retain unknown denominators;
they cannot be backfilled. A later criterion consumer must still establish valid passing,
failed and unresolved evidence against those requirements before closing the coverage gate.

## Verification

The final combined policy/statistics/whole-attempt/reporting/ledger-coverage suite passed
69 tests in 456.39 seconds. It includes actual controlled coordinator/scorer/adjudication
receipts and current-authority denial paths, with explicit owned admission/runtime fixtures.
The first combined run retained 68 passes and one floating-point equality assertion failure
(`0.1` versus `0.09999999999999998`); the parity test now uses numeric tolerance. Review also
removed task-level intervals for stability repeats and anchored final wall time to the
verified outcome/adjudication checkpoint. The final run covers those changes. No historical
task execution, paid request or release promotion was performed by these tests.
