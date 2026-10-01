# ADR-024: Prospectively bind criterion evidence coverage and completeness

Status: implemented prospectively with scoped concrete-consumer verification. No historical result.

## Decision and interpretation

The protocol requires at least 60% strict success, zero observed false-ready candidates and
100% evidence completeness. Completeness must not erase unsuccessful tasks, turn an unrun check
into a pass, or require every task to succeed merely to record its failure honestly. For the
explicitly selected `current-final-criterion-evidence-v1` profile, enforce two checks:

1. Every assigned requirement has a current validated disposition from its completed attempt.
   A verified early failure may establish why later stages did not execute. An unstarted task,
   missing proof or unknown operation does not establish that disposition.
2. Every candidate declared ready under the original A/B policy has current passing evidence
   for every requirement. Failed, unexecuted, unsupported or pending-manual criteria fail this
   check; unresolved judgments or unavailable evidence cannot pass it.

These clarify the 100% completeness target without changing strict-success, false-ready,
infrastructure, cost or operational thresholds. A complete failure record remains unsuccessful.
Criterion acceptance coverage is still passing criteria divided by **all** frozen assigned
criteria. It never becomes 100% passing coverage merely because failures are documented.
All phase assignments, including stability attempts, must satisfy the evidence checks;
primary/stability rates remain separate and repeats cannot replace primary outcomes.

## Concrete evidence join

After replaying and matching sealed artifacts, candidate and semantic consumers retain private
in-process criterion identity/type/status tuples. They do not accept these tuples from JSON or
serialize them. The whole-attempt reader joins them only after validating the full stage chain,
allowed early exit, receipts, original policies, current permissions and repository/candidate
bindings. Parsed summary counts alone cannot reconstruct this join.

A supported automated criterion passes only when its final-candidate test and the independent
semantic finding for that same criterion passed, and trusted acceptance/regression checks passed.
Matching marginal counts cannot substitute for matching criteria. A test failure or negative
semantic finding is retained; a test that never executed remains unexecuted. Missing required
semantic/deterministic evidence remains unresolved. Manual criteria remain pending and unsupported
types remain unsupported; automated judgments cannot manufacture a human decision.

Serialized results contain only binding digests and counts. Source, descriptions, criterion IDs,
test identifiers, diagnostics and model text stay out of reporting. Whole-attempt consumption
schema 5 carries the result; original sealed artifacts remain unchanged. The reduced fields are
descriptive evidence, not an independent authority token.

## Prospective policy and reporting

The controller must explicitly select this profile while freezing the reporting policy, with the
complete original requirement inventory and statistical policy. Missing inventory is refused.
An existing policy cannot acquire the profile through a later freeze or read. Older policies
retain unavailable gate results even when newer readers can describe joint counts.

Statistics match the task manifest and criterion identity/type/count to the original inventory,
retaining all missing assignments. Passing coverage and recorded-disposition coverage have
separate integer numerators/denominators and no criterion-level binomial intervals.

Phase `evidence_completeness_gate` checks all disposition records; `criterion_coverage_gate`
checks all declared-ready candidates' required passing evidence. No ready candidates yields
NOT_APPLICABLE when all readiness is known. Unknown readiness blocks the check. Zero success
still fails the separate success threshold. Neither check establishes absence of defects,
general review independence, manual approval, operational safety, full spending or pilot signoff.
Phase promotion and execution authority remain separate and are not granted by this change.
