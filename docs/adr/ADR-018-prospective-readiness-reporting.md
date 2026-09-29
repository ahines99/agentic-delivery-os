# ADR-018: Freeze the A/B readiness declaration before execution

Status: accepted and implemented prospective reporting policy, 2026-09-29.
No historical campaign has executed under this profile.

## Context

The evaluation protocol measures candidates declared ready by an arm that subsequently
fail independent final scoring. The candidate engine already seals distinct pre-scoring
statuses: `BUILD_VERIFIED` for builder-only A, `REVIEW_APPROVED` for independently reviewed
B, and `FAILED` for unsuccessful production. Deriving readiness from final scoring would
remove precisely the false-ready cases the comparison is intended to measure.

## Decision

Use the explicit `sealed-ab-readiness-v1` reporting profile. Arm A declares comparison
readiness at `BUILD_VERIFIED`; arm B declares it at `REVIEW_APPROVED`. `FAILED` declares
neither arm ready. Other arm/status combinations are unsupported and cannot be silently
interpreted. These are experimental declarations, not product publication or merge authority.
Product delivery retains its independent review and complete acceptance requirements.

Pin this policy as the first event of the registered campaign journal, before any phase
is opened or intent recorded and before any canonical campaign account exists. Bind the
policy artifact to the campaign and its frozen scoring-code commit. Inspection reconstructs
that original event and artifact; a missing policy cannot be backfilled after phase opening.
Existing campaign artifacts, schedules, grants, outcomes and older journal histories are
unchanged. Older histories without this policy remain inspectable but cannot support this
new profile's aggregate readiness claims. Old readers reject the new event kind.

Strict-success denominators contain every frozen primary assignment, including unavailable
outcomes. Unavailable proof remains explicitly unavailable rather than receiving an invented
scored-failure label. Stability repeats remain separate. A zero ready denominator is not
applicable, never a zero false-ready rate. Missing readiness or final-scoring evidence cannot
establish a passed false-ready/evidence gate. Final PASS/FAIL/adjudication never rewrites the
candidate's original declaration.

## Boundaries

The journal records a trusted controller's prospective decision; it does not authenticate a
malicious database owner or serialize arbitrary allocation outside the journal protocol.
The wrapper checks canonical account absence before pinning and rejects accounts whose
creation predates the policy during inspection. The controller must use the one pinned
journal and enforce its existing execution authority, budgets and serial dispatch controls.

The declaration mapping does not itself consume candidate proof, compute aggregate results,
reconcile costs, grant phase promotion or authorize a pilot. Reports still require current
concrete whole-attempt consumers, retained missing/uncertain outcomes and complete cost and
operational evidence. No observed historical accuracy, false-ready rate or review benefit
follows from freezing the policy.

Fifteen owned policy tests passed in 27.26 seconds. The preceding combined run passed
69 journal/dispatch/policy checks and retained one fixture failure: the proposed foreign
commit equaled the original fixture commit. The fixture now asserts that its replacement
differs before testing refusal. No production change was needed for that correction.
The combined run exercised all 55 pre-existing journal and dispatch-journal checks.
