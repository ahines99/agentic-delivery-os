# Calibration subjects and actual execution scope

`evaluation/qualification_v2.py` supports an explicit calibration-only review subject.
It makes unsafe or ambiguous hypothetical requests available to the evaluator without
claiming that those requests were executed, qualified or authorized. It does not run
models or code, grant rights, spend funds, or qualify a historical task.

## Protected input

`CalibrationReviewSubject` contains `schema_version=1`,
`kind=synthetic-calibration-review-subject`, a neutral task ID, exact subject manifest
digest, `execution_anchor_artifact`, the inert subject `WorkItem`, and six separately
authored supporting-document references (`rights`, `risk`, `runtime`, `leakage`,
`family`, `oracle`). Unknown fields are rejected. There is no expected verdict,
expected finding, reference solution or execution command field.

Create the subject with a temporary 64-character digest, calculate
`subject_manifest_digest(subject)`, and replace `task_manifest_digest` with that
value. The helper hashes every exact subject field except the recursive digest
itself. Store the completed document and pass its artifact digest to the existing
`assemble_review_context(..., qualification_input_artifact=..., ...)` API. Changed
subject wording, supporting documents or execution anchor require a new binding.

The anchor must be a complete `QualificationInput` with project-owned
`SyntheticProvenance`, development split and a safe Tier 0/1 execution task. Its
repository must match the subject repository. All twelve baseline/reference,
acceptance/regression receipts are reconstructed through the existing deterministic
validator; missing, stale or reused runtime identities fail closed. An anchor cannot
be another subject. Source/oracle snapshots, immutable oracle preservation, approved
commands and frozen nodes retain their existing checks.

The anchor producer and caller must separately validate current authorization and
actual settled runtime ledger provenance. This context module reconstructs immutable
artifacts; it does not authenticate arbitrary writers or verify the execution ledger.
The unit fixture receipts are synthetic and are not evidence that runtime occurred.

## Model-visible distinction

Historical review contexts keep their previous serialized shape. Subject contexts
use `FrozenCalibrationEvidenceV2`, an explicit subtype accepted by `ReviewContextV2`:

- Top-level `task_spec` describes only the hypothetical review subject, including its
  actual declared risk and ambiguities. All six subject `declared_checks` are
  `PENDING`; no successful eligibility claim is invented for a negative case.
- `purpose=CALIBRATION_ONLY` and `subject_executed=false` remain explicit.
- `execution_scope` identifies the safe anchor input digest, task/manifest identity,
  task specification, original declared checks, source snapshot digest and all twelve
  runtime operation IDs. Its scope is `SAFE_ANCHOR_ONLY`.
- The source, oracle, image, nodes, normalized outcomes and license/authorization
  documents apply to that safe anchor. They do not establish behavior or rights for
  hypothetical actions described by the subject.
- The six semantic supporting documents describe the subject separately. They must
  have distinct digests and cannot alias anchor documents, receipts, rubric, source,
  oracle or known reference artifacts. The synthetic provenance
  `authoring_artifact` identifies the full private authored aggregate, including
  reference code and expected judgments. That exact artifact is forbidden as any
  supporting document or rubric through both the ordinary anchor and subject routes,
  before its bytes can be opened as model evidence. Findings cite the subject document
  as well as the existing required anchor evidence. This permits an evaluator to
  explain absent coverage or a mismatch without inventing execution.

Expected decisions and mandatory findings remain solely in the protected
`CalibrationSpec`, outside the model context. Use neutral subject IDs and prose;
do not encode expected categories, answers or reference solutions in supporting
text. Hash and schema checks cannot establish semantic absence of answer leakage.
Trusted authors/importers remain responsible for this boundary. The qualifier prompt
and `ReviewOutputV2` schema are unchanged.

The existing calibration loader reconstructs the new context union without a separate
bypass. Calibration still measures observed structured decisions against its frozen
expectations, under its existing explicit grants and finite budgets. A successful
controlled test is not evidence of real judge accuracy or human benefit.

## No promotion to qualification

`resolve_reviews` explicitly refuses calibration subject contexts, even if a caller
changes their pending flags or supplies an apparently favorable model output. A
subject document cannot parse as the controller's `QualificationInput`. Removing the
subtype fields from a context also fails immutable reconstruction. The ordinary
qualification provenance union now accepts honest synthetic fixture provenance, but
the legacy historical validator explicitly rejects it; historical serialization and
historical provenance requirements remain unchanged.

These boundaries preserve calibration diagnostics without authorizing historical
worker exports, scoring, campaign admission, publication, merge or deployment.
