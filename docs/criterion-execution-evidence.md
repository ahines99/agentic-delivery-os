# Final-candidate criterion test evidence

The protected candidate consumer replays the original iteration engine from concretely
validated model and runner receipts, requires the reconstructed result to match the sealed
artifacts, and then counts the final candidate's criterion test summaries. Version 2 of
`ValidatedSealedCandidate` carries these counts; version 4 of `ValidatedCompletedAttempt`
forwards them even when candidate or deterministic scoring failure prevents semantic scoring.
No execution authority, artifacts, model calls or ledger writes are created by this read.

Each observed receipt must describe the final candidate snapshot and the matching criterion
command. The supported candidate engine executes unit/integration tests. A failing test is
retained as failed evidence. A failed final validation or baseline with no criterion execution
is `not_executed`, not a fabricated failed test. Passing tests from an earlier repair round
cannot supply evidence for a later snapshot. A reviewer rejection does not rewrite actual
passing test observations into failures.

The exported counts include a criterion identity/type digest, total required count and counts
by verification type. They contain no criterion IDs, descriptions, commands, test identifiers,
diagnostics, source or private model output. The reducer accepts the concrete consumer's local
reconstruction; it is not an authority boundary for arbitrary submitted summaries.

When the original report policy pins a [requirement inventory](campaign-criterion-inventory.md),
phase statistics match the task manifest, criterion identity/type hash, total and type counts.
Every assigned requirement remains in the denominator. Missing attempt proof contributes
`unavailable`; an observed non-execution and unavailable proof remain distinct. Without an
inventory, aggregate counts and coverage are null rather than inferred from completed tasks.
Primary and stability populations remain separate.

`candidate_criterion_test_coverage` is passing final-candidate criterion test evidence divided
by all frozen assigned requirements. It carries integer numerator/denominator and no binomial
confidence interval: criteria within a task are not independent experimental units. These are
builder-proposed test mappings with verified execution, not a claim that the mapping proves
the requested behavior. [Independent semantic judgments](criterion-judgments.md), protected
acceptance/regression checks and their failures remain separate. No human review is inferred
for manual-type requirements.

This metric does not establish complete required evidence or authorize promotion. In particular,
unexecuted criteria do not become passing coverage merely because the early failure itself is
well evidenced. The existing required-evidence, operational, infrastructure, full program-cost
and pilot gates remain open. The coverage gate stays UNAVAILABLE until the complete required
evidence contract is implemented and verified.

## Verification

Owned reducer/statistics tests distinguish final passing/failing receipts, baseline and final
validation failures, earlier-round staleness, reviewer rejection, mismatched identities/types,
missing proof and the complete frozen denominator. Concrete candidate and whole-attempt reader
checks separately exercise actual controlled receipts with effects denied during inspection.
All fixtures are authored development data; no historical result or efficacy is claimed.


The reducer/statistics scope passed 25 tests in 0.91 seconds. Concrete candidate/whole-attempt
readers passed eight cases (50 deselected) in 44.65 seconds; aggregate reporting passed four
cases (18 deselected) in 90.48 seconds. After composing mandatory program enrollment, the
reader cases still passed but four aggregate fixtures failed setup because they deleted an
account with a retained lifecycle row. The separately verified fixture correction preserved
production constraints; the final combined aggregate cases then passed in 102.06 seconds.
These overlapping scopes are not summed. Lint/format, type checks and package builds passed;
exact-head full CI and independent review remain required.
