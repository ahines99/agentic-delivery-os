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
