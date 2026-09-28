# Honest synthetic fixture preparation

`evaluation/synthetic_types.py` defines project-owned development fixtures separately from
historical benchmark tasks. A `SyntheticTask` has `kind="project-owned-synthetic"`,
`purpose="SYNTHETIC_VALIDATION"`, development-only split and an explicit construction-code Git
revision. That revision identifies the code used to construct the fixture; it does not claim
that generated source files existed at that commit. Artifact digests bind those actual bytes.
There is no historical issue URL, base revision, accepted fix commit or GitHub license URL.
The required `authoring_artifact` binds the complete protected authored example into the task
digest and usage authorization, including the exact inert review subject and private expectations.
Those private contents remain outside exported task and model projections.

Preparation keeps its existing three-reference `PreparationRequest` and non-admitting
`PreparedQualification` result. The public `parse_task`, `parse_provenance` and
`parse_usage_authorization` functions dispatch documents carrying the synthetic kind to strict
leaf contracts. Documents without that kind retain historical validation; unknown or mixed
kinds fail. Historical serialized contracts, task digests and license gates are unchanged.

## Evidence and authority

Synthetic provenance binds the configured repository, construction revision, source snapshot,
license evidence and usage authorization. The license evidence binds a relative source-file
path, substantive text digest and immutable source bundle. This repository has no public
license grant. Newly authored internal toy fixtures can use
`LicenseRef-Project-Owned-Internal` and a `FIXTURE_RIGHTS.txt` document that records their narrow
construction and internal model-processing purpose. This identifier does not enter the
historical MIT/BSD allowlist and does not grant public redistribution rights.

The usage authorization is a trusted controller attestation, pinned by the current preparation
policy. It binds the exact task digest, repository, construction revision, license evidence,
`PROJECT_OWNED_FIXTURE_AND_INTERNAL_MODEL_PROCESSING` scope, issuer, rationale and validity
window. These documents do not independently establish ownership or legal clearance. Their
producer and policy authority remain trusted; merely providing text with a hash is insufficient
without that authorization.

The reference provenance records `method="AUTHORED_FIXTURE_REFERENCE"` and binds the exact
source, oracle, reference snapshot and patch. It makes no historical acceptance claim.

## Shared execution safeguards and boundaries

Both paths use the same configured repository and model-data permission, pinned image, risk
policy, budget, command allowlist, disjoint artifact/worker scopes, bounded text snapshots,
oracle collision rules and strict in-memory patch application. The authored reference must
reproduce the declared reference snapshot exactly while preserving original tests, rights text
and protected runner/control files. No shell applies the patch. Preparation executes nothing,
makes no model calls, writes no artifacts and exports no oracle or solution text.

Synthetic execution subjects still require supported risk tier 0/1 and acceptance criteria.
An intentionally ineligible calibration review subject is a separate contract, not permission
to execute a dangerous synthetic repository. `SyntheticTask.worker_input` and
`validate_qualification` always deny historical campaign use. No purpose argument, changed
split or historical manifest loader can promote a synthetic record into historical admission.

Tests use newly authored toy source and test-policy attestations. They cover read-only successful
preparation, expiry/revocation, identity tampering, historical conversion refusal, scope/image/risk
checks and protected reference changes. Passing these tests does not qualify a historical ticket
or establish benchmark performance.
