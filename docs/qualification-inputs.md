# Review inputs from completed execution

`evaluation.qualification_inputs.materialize_qualification_input` creates a private
`QualificationInput` from a completed deterministic runtime. It makes no model call,
starts no Docker job, grants no admission and allocates no new spending. Calibration
preparation and the full qualification controller use the same producer.

The caller supplies the exact runtime request and evidence reference, original runtime
authorization, current settings/preparation policy, private stores, worker root, dedicated
evaluation ledger, trusted current time, and six imported supporting findings. The producer
revalidates the complete runtime using its trusted completion checkpoint and actual settled
operation receipts. Current rights, configuration and store separation must still hold.
A caller-authored execution JSON document cannot replace that ledger chain.

Only verified runtime artifacts are copied into the protected review store, preserving exact
digests. The input's task, source, oracle, reference identities, commands, frozen collection
and twelve execution receipts come from the validated request. Imported supporting findings
must cover all six roles and cite their exact evidence. They remain controller attestations;
the producer does not change pending semantic judgments into passing reviews.

The immutable `runtime-review-input-v1` checkpoint binds the assembled input to its original
runtime account. Exact repeat calls reuse the same identity without execution or cost. Changed
findings cannot overwrite the original checkpoint. As with other content-addressed artifacts,
a failed final checkpoint can leave unreachable private blobs; this is not a retention guarantee.

The full qualification controller separately seals `qualification-input-v2` and requires its
passing preliminary findings, calibrated independent reviews, closed accounting and current
admission authority. A calibration subject may instead refer to the safe synthetic input under
the [inert subject contract](calibration-subjects.md); that subject is never a historical task
or permission to execute its requested behavior.

Focused tests reconstruct the full controlled runtime chain, compare every copied receipt,
preserve pending findings and account spending, and reject missing checkpoints, unknown
operations, revoked current settings, missing evidence and changed findings on resume. The
existing complete-controller regressions exercise the integrated producer. These tests use
explicitly synthetic inputs; actual owned-fixture Docker preparation is recorded separately.

## Explicit derived historical inputs

The [derived-input contract](derived-qualification-inputs.md) records the complete
binding, exclusion and active-expiry behavior.

The versioned [historical import](historical-import-v2.md) path materializes a schema-2
`historical-derived-qualification-input` wrapper around the unchanged schema-1
`QualificationInput`. It binds the exact original task, provenance and derived reference
artifacts. Both runtime and qualification checkpoints use the outer artifact digest.
Controller, protected review and current admission resolve that same identity; removing
the wrapper or swapping a current preparation reference is refused.

The resolver reconstructs the full derivation and provider-reported linkage. Acceptance
selectors must equal the frozen derivation, original regression selectors must exclude
the oracle namespace, and model-visible task wording must match the frozen issue body
with a neutral title. The currently captured upstream title is retained privately and
excluded from supporting evidence because its historical wording is unverified.

The forbidden-artifact set comes from validated records, including accepted snapshots,
patch/reference bytes, acquisition inventories, relocated test source artifacts and
known aggregate records. Only the separately authorized source/oracle channels expose
their intended contents to protected reviewers. Supporting findings remain trusted
producer attestations: these checks do not prove that arbitrary free text contains no
semantic answer leakage.

Derived data use requires both the parent authorization and the explicit derived-data
authorization to be current and pinned by the unchanged trusted preparation policy.
Read-only content validation alone does not grant current use or establish worker-store
separation. Existing v1 and synthetic record serialization and frozen review output
remain unchanged. No historical qualification follows merely from resolving a wrapper.
