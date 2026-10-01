# Joint criterion acceptance evidence

[ADR-024](adr/ADR-024-prospective-criterion-evidence-gates.md) joins concretely validated final
test receipts and independent semantic findings by criterion, after whole-attempt reconstruction.
The parent proof binds the original campaign, task manifest, candidate, policies and operations
under current authority. Equal aggregate pass counts cannot prove the same criteria passed both
checks. Private in-process join facts are excluded from JSON; parsed counts cannot supply them.

The counts distinguish passing, failing, unresolved, not executed, pending manual, unsupported
and unavailable criteria. Passing requires a supported final test and the same criterion's
independent semantic finding to pass, plus trusted acceptance/regression checks. Human approval
is never inferred. Early failures remain recorded dispositions, not fabricated later test runs.

`freeze_reporting_policy(..., criterion_inventory_artifact=...,
criterion_evidence_profile="current-final-criterion-evidence-v1")` explicitly pins this policy
before phase opening or account allocation. Missing inventory is refused. Repeating a freeze
cannot add the profile to an older policy after outcomes exist.

Reports retain all frozen requirements, including unstarted tasks and missing proof:

| Output | Meaning |
| --- | --- |
| `criterion_acceptance_coverage` | Current passing joint criterion evidence / all assigned requirements |
| `criterion_disposition_coverage` | Requirements with validated completed-attempt dispositions / all assigned requirements |
| `complete_criterion_dispositions` | 100% disposition coverage under the originally selected profile |
| `declared_ready_criterion_evidence` | Every declared-ready candidate has passing evidence for every requirement |
| Phase `evidence_completeness_gate` | All primary and stability groups have complete disposition evidence |
| Phase `criterion_coverage_gate` | All primary and stability groups satisfy declared-ready criterion evidence |

A complete recorded failure can raise disposition coverage while leaving passing coverage
unchanged. Declaring that failed candidate ready still fails the criterion gate. An unresolved
semantic verdict cannot pass the readiness check. Missing stability proof blocks phase evidence
completeness without changing primary success rates. Without the prospectively pinned profile,
gate results stay UNAVAILABLE. Promotion remains false until the other operational, infrastructure,
cost, corpus and human signoff requirements are satisfied.

Negative or unresolved non-criterion rubric findings and new review concerns still block the
separate final-verdict/false-ready checks even when the individual criterion counts all pass.

## Verification

The existing execution/judgment/statistics/policy scope passed 61 tests in 34.88 seconds.
Inventory/profile and the initial joint-evidence scope passed 40 tests in 78.13 seconds;
the final expanded 20-case joint scope passed in 0.69 seconds. These include mismatched
criterion populations, disjoint marginal successes, serialized-count refusal, private-fact
redaction, manual/unsupported criteria, recorded early failure, missing stability attempts,
and refusal to backfill an existing policy.

All 44 concrete whole-attempt/aggregate reporting cases passed in 490.79 seconds. They include
controlled actual candidate/scorer/adjudication receipts, early failures, original policies,
the new prospective profile and current-permission denial. Fixtures retain their explicit
owned qualification/calibration/runtime boundaries; this is not a historical campaign.
Production source stayed fixed during these runs. Counts overlap and are not summed.
Ruff/format (386 files), mypy (121 sources), and source/wheel builds passed. Exact-head full CI
and independent review remain required; no paid request or protected historical payload was used.
