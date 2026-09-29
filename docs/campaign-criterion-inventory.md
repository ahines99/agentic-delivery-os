# Prospective campaign requirement inventory

`capture_criterion_inventory(...)` gives the trusted protected controller a way to capture
requirement denominators before any reporting policy, phase or canonical attempt account
exists. It accepts the exact task set bound by the registered execution campaign and a
concrete current `QualificationAuthority`. This is a protected controller API; historical
task payloads must never be supplied through an interactive implementation-agent context.

For each task, the capture matches the manifest digest, qualification artifact, split,
family and repository to the frozen campaign, then revalidates current campaign-use
qualification. It checks the campaign's calibration/rubric binding and rechecks the empty
journal and absence of canonical accounts before and after writing the metadata artifact.
It makes no model call, account allocation, ledger mutation or journal event.

The artifact contains one row per unique task: existing task identity/provenance, total
required criteria, counts by verification type, and a digest of criterion IDs/types.
It exports no criterion descriptions, raw criterion IDs, source, test bodies, findings,
reasons or citations. Counts must include every verification type and sum exactly to the
positive required count. Task rows are canonical and complete, including unrun sealed tasks.

## Pinning and consumption

Pass the artifact as `criterion_inventory_artifact` to `freeze_reporting_policy(...)`, using
the same controller-owned metadata artifact store for the inventory and policy. The first
policy event pins the exact reference. Validation checks the original campaign, registration,
manifest, ordered task set, qualification references and capture chronology. Missing,
duplicated, reordered, foreign or internally inconsistent rows cause refusal. An existing
policy cannot acquire a new inventory through repeated freezing, even if the inventory was
captured earlier. Policies without an inventory remain readable with unknown denominators.

The aggregate report reopens only the pinned metadata. It does not load unstarted protected
task contexts or invoke qualification/scoring to compute denominators. Each arm's primary
and stability summaries include `required_criteria` and `required_criteria_by_verification_type`.
Repeats retain their own attempted-criterion counts and never alter primary denominators.
Missing inventory is null, never zero. Existing frozen campaigns, manifest digests,
registrations and policies are not rewritten.

## Trust and limits

The protected controller and its artifact store remain trusted for the original capture.
An artifact hash identifies content; it is not a signature authenticating a malicious
database/artifact owner. The metadata-only reader cannot independently recover requirement
counts from an opaque manifest digest. Builder/model inputs must not select or write this
policy store. The current guard authorizes the full protected collection and metadata
export during capture, and current metadata use during reporting. A denial is sanitized
and does not return a partial inventory; a race after an artifact write may leave an
unreferenced artifact but grants no execution or policy authority.

These are verified capture denominators within that controller boundary, not passing
criterion evidence. `criteria_scored` and `execution_authorized` remain false. The report's
criterion-coverage gate stays unavailable until a concrete per-criterion consumer binds
valid passing, failed and unresolved evidence to these requirements and verification types.
Manual requirements are counted separately; counting them does not supply a human decision.
No phase promotion, pilot signoff or historical accuracy claim follows from this inventory.

## Verification

Sixty-six combined inventory, reporting-policy, phase-statistics and aggregate-report tests
passed in 188.43 seconds. A final capture-permission revocation check passed in 5.90 seconds.
The inventory cases use owned manifests, an explicit qualification/calibration stand-in,
and actual journal/artifact operations. They check canonical complete capture, missing or
duplicate inputs, changed manifests, qualification denial, no partial export, capture after
policy/phase/allocation, malformed counts/bindings, chronology, retrospective pin refusal,
unknown legacy denominators and reporting without protected-task loads or writes.
They establish metadata behavior within the stated controller boundary, not real corpus
qualification, passing criteria, a historical campaign or numerical promotion.
