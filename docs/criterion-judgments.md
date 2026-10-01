# Criterion judgment reporting

The protected completed-semantic reader now returns content-free criterion judgment
counts after reconstructing actual review operations, citations, calibration, original
execution terms and current reporting permission. Its output is version 2. The
whole-attempt reader carries those counts in its version-3 consumption output. Original
execution outcomes, grants, prompts, model schemas and stored adjudications are unchanged.
These are freshly reconstructed reporting outputs, not a rewrite of prior evidence.

The subsequent [joint criterion profile](criterion-acceptance-evidence.md) joins these findings
with final-candidate execution in whole-attempt schema 5. The protected consumers retain private
in-process join facts, excluded from JSON. Standalone serialized counts supply no join authority.

The counts include a hash of sorted criterion identities and verification types, the
required count, and PASS/FAIL/UNRESOLVED totals by verification type. They export no raw
criterion identities, descriptions, model reasons, citations, source, or reference answers.
Historical processing stays inside protected readers; implementation tests use owned data.

## Interpretation

- Two valid initial scorers retain each agreed criterion status. A differing status is
  UNRESOLVED until concretely validated adjudication resolves it. Other agreed criteria
  do not become failures merely because the overall verdict is unresolved.
- Invalid initial review evidence yields UNRESOLVED for every criterion. A consumed but
  invalid adjudication likewise yields no resolved criterion judgments.
- Valid adjudication uses the reconstructed merged findings. It preserves original
  agreements and carries the count of blocking new concerns separately. Concerns can block
  the overall verdict even when all criterion judgments pass; they do not rewrite agreed
  statuses. A null concern count means no valid adjudication merge was consumed, not zero.
- A candidate or deterministic failure before semantic scoring has no semantic judgment
  summary. Its whole-attempt failure and actual deterministic evidence remain separate.

When the original reporting policy pins a [requirement inventory](campaign-criterion-inventory.md),
phase statistics check each completed task's manifest, criterion identity hash, total and
verification-type counts against it. Mismatch refuses the report. They sum passing,
failing and unresolved semantic judgments, and count missing judgments as UNSCORED using
the full assigned inventory. This includes unstarted assignments, unavailable completed
proof and early failures. Primary and stability populations remain separate. Without an
original inventory, aggregate criterion counts remain null rather than inferring a complete
denominator from only the finished tasks. Per-attempt available judgments remain inspectable.

These fields describe calibrated automated judgments, not measured per-criterion test
coverage or human approval. Manual-review type counts never supply an actual human decision.
Separate [final-candidate criterion test evidence](criterion-execution-evidence.md) now records
validated passing/failing tests, explicit non-execution and unavailable assignment proof.
The numeric reducer is not an authority boundary: only the concrete protected consumer
validates source evidence. Builder/model-supplied summaries are not accepted as completion
proof. The report still rereads actual proof, accounts, inventory policy and current guards.

The criterion-coverage gate remains UNAVAILABLE. Complete required evidence is not the
same as every task or criterion passing: a well-evidenced failure remains a failure without
necessarily being missing evidence. Operational, infrastructure and complete-program-cost
gates also remain separate. These counts do not authorize promotion, a pilot or paid work.

## Verification scope

Owned arithmetic tests cover partial agreement, invalid evidence, concerns, privacy of
exported metadata, manual-type separation, full denominators, early/unrun assignments and
manifest/identity/count/type mismatches. Concrete consumer and aggregate tests reconstruct
controlled A/B reviews and adjudication receipts with effects forbidden during reporting.
Qualification/calibration/runtime admission retain explicit fixture stand-ins; the aggregate
integration uses authored prospective inventory metadata for owned manifests. None of these
tests is historical task qualification, historical scoring, or a release efficacy result.


The counts/statistics/inventory scope passed 50 tests in 52.76 seconds. The broader
semantic/whole-attempt/aggregate scope passed 60 tests and retained four setup errors in
782.76 seconds: the new owned inventory fixture incorrectly read a manifest digest from
`JournalRegistration` instead of the frozen `ExecutionCampaign`. The corrected four actual
aggregate cases passed in 85.54 seconds; production code was unchanged. The already-running
broader process had imported the original fixture before that correction. Ruff/format,
mypy, package builds, documentation links and staged secret scanning passed. These are
scoped checks, not a full new-head suite or an independently reviewed historical result.
