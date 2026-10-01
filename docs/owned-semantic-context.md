# Owned semantic calibration contexts

`OwnedSemanticContextAuthority` in `evaluation/semantic_owned_context.py` constructs
protected contexts from a concrete `OwnedSemanticRuntime`, its exact request and
completed evidence artifact, and a trusted current rubric allowlist. It neither
executes models nor performs calibration, adjudication or historical admission.

`assemble(stage=..., context_id=..., rubric_artifact=...)` explicitly writes three
immutable projection artifacts into the runtime's private output store: authored
baseline plus original regression source, candidate plus original regression source,
and the frozen acceptance oracle. These maps come exclusively from the currently
authorized `SemanticSubject`; no caller-supplied replacement files are accepted.
`prepare_owned_semantic_projections` exposes the same preparation independently.
The concrete runtime reconstructs its actual ledger and receipts before and after
these writes. Failed later validation can leave harmless unreferenced immutable maps;
it never returns an authorized context or erases the failed attempt.

`validate(context)` is read-only. It derives the exact projection bytes again, requires
their existing content-addressed artifacts, and rebuilds the entire context under the
current runtime and rubric authority. It never repairs a missing projection, creates
an account, reserves budget, reruns Docker or calls a model. A completed owned
execution may remain inspectable after its original execution deadline only while the
runtime's current data-use policy still permits it; the runtime separately validates
that all original effects completed inside their original finite grant.

The model-visible evidence has explicit purpose `OWNED_DEVELOPMENT_CALIBRATION`,
`baseline_executed: false` and `admitted: false`. Only the candidate was tested against
the included acceptance/regression sources. Requirements and criteria come directly
from the owned subject, without a fabricated `HistoricalTask`, historical qualification,
or campaign record. It binds the original subject, request, grant, runtime checkpoint,
executed snapshot, three operation receipts and normalized test evidence. Authored
baseline bytes are provided for inspection, never presented as an observed baseline
test result. Source strings retain whitespace and line coordinates.

No expected verdict, category, diagnostic counterexample or reference solution is read
by this adapter or added to its context. Raw sandbox output and arbitrary report fields
are omitted. Rubrics require an exact trusted allowlist; structured aggregates and known
subject/evidence/projection artifacts cannot be used as rubrics. As with historical
contexts, trusted rubric authors must not copy protected answers into new prose: hashes
and schemas do not detect semantic copying or authenticate an arbitrary storage writer.

The shared `SemanticScoringContext` has an explicit evidence union and matching purpose.
Historical serialization remains unchanged. Historical reconstruction rejects owned
contexts, and owned authority rejects historical contexts. The shared output validator
checks the same exact criteria, three integrity findings and actual citation coordinates
for either purpose. Structural `PASS` is not a measured judgment, successful calibration,
historical strict success or release readiness. Initial scorer roles remain separate;
adjudication remains unavailable in this slice.

Owned tests exercise current-policy changes, rehashed substitutions, missing projections,
exact bytes, purpose confusion and write-free validation. One marked integration case
uses the real pinned Docker collector and SQLite ledger to build and then reconstruct a
candidate-only context with zero model tokens. Other cases use controlled runner reports
and actual accounting. None is a historical benchmark or a semantic model evaluation.
