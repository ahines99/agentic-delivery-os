# Protected accepted-fix linkage and v2 historical import

`historical_linkage` validates metadata captured by a trusted controller from the fixed
GitHub GraphQL endpoint. Its exported `LINKAGE_QUERY` contains no issue body/title,
commit message, author, login or email. The caller must use that exact query, explicitly
selected public repository, bounded credential-safe transport, and two equal captures;
this module makes no network request and discovers no credentials.

`freeze_historical_linkage(first_response, second_response, *, derivation_artifact,
requirements_capture_artifact, first_captured_at, captured_at, protected_artifacts,
worker_roots, now=None)` validates and freezes protected metadata. Both response objects
have the complete GraphQL `{data: {repository: ...}}` structure from `LINKAGE_QUERY`.
The return is an artifact digest. `validate_historical_linkage(artifact, *,
protected_artifacts, derivation, now=None)` reconstructs every binding without writes.
The caller supplies current trusted time when replaying deterministic validations.

The initial profile requires one public repository identity, a complete accepted commit
with exactly one parent equal to the acquired baseline, its exact acquired tree, and a
merged PR whose merge commit equals that accepted commit. A complete bounded issue
closed-event connection must contain exactly one event whose closer is that exact PR.
The issue ID/number/URL and repository node/numeric IDs must match the protected issue
requirements capture. Missing metadata, pagination, duplicate matching closure,
commit-only or other unsupported closer kinds, merge commits with multiple parents,
redirects represented as changed identities, or inconsistent captures refuse the profile.

Acceptance time is the PR's `mergedAt`. The commit's `committedDate` must be no later,
but is not substituted for acceptance time. Requirements creation/edit time must strictly
precede that solution commit timestamp as well as merge; equality or later edits refuse
the profile. Git timestamps/provider history still do not establish the earliest public
solution disclosure or archival truth. The closing event must be no earlier than merge,
and all capture times must be no later than current trusted time. Full baseline/accepted
acquisitions are read and reconstructed through the derivation; neither snapshot capture
alone asserts a parent or acceptance timestamp.

The issue capture's body/title digests and complete recorded edit metadata are rechecked
using the same requirements-capture rules. Its title remains explicitly current and not
historically verified. Provider-reported no-edit metadata remains an inference, not an
archival record. No rights determination or admission follows from linkage validation.

These are trusted-caller provider assertions, not cryptographically authenticated GitHub
responses. A content hash prevents unnoticed byte changes but cannot attest who fetched
an arbitrary fabricated artifact. The controller must protect artifact writers and
perform the fixed-origin acquisition. Neither this module nor its record claims to
verify transport provenance from a stored label. The record explicitly retains
`cryptographic_authenticity=false`, `rights_cleared=false` and `admitted=false`.

All responses and referenced source remain evaluator-only. Validation and encoded-size
checks happen before real artifact writes; write failure may leave an unreferenced
artifact, never a successful partial record. Constant errors exclude upstream payloads.
Synthetic tests exercise mismatched IDs/trees/parents, forged merged/close chronology,
wrong issue/body, incomplete event pages, private metadata, rehashed envelopes and
identical read-only reconstruction. No real historical provider payload or execution
was used during implementation.

Primary API semantics: [GitHub issue/ClosedEvent fields](https://docs.github.com/en/graphql/reference/issues)
identify the object that caused closure; [PR fields](https://docs.github.com/en/graphql/reference/pulls)
distinguish merge time and merge commit. The REST documentation likewise distinguishes
[a commit-linked closed event](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types)
from a generic reference. Prose references alone are not accepted by this profile.

## Explicit derived import and rights

`import_historical_task_v2(HistoricalImportRequestV2(...), ...)` is an explicit route;
the v1 `import_historical_task` and all existing v1 serialized fields remain unchanged.
The schema-2 acquisition envelope must bind the complete baseline inventory, full
accepted snapshot, exact derivation/linkage/requirements capture, pending task digest,
source metadata and both authorization references. Preparation's schema-2 reference
must name these same artifacts. Rehashed mismatched envelopes refuse before writes.
The importer requires the task description to equal the captured body after the domain
contract's outer whitespace stripping; its title must be the neutral `Historical issue #<number>`.
The current captured issue title is never promoted into historical task requirements.
The same projection is enforced at shared preparation/resolver/current-use entry
points, because callers can prepare a task without importing it. Separate owned
tests reject fully rebound alternate wording through those direct paths. Active
runtime/model guards honor the earlier data-authorization expiration.

The separate `DerivedReferenceAuthorization` is an explicit controller data attestation
for `HISTORICAL_EVALUATION_DATA_PROCESSING`. It binds the parent `UsageAuthorization`
digest, the same issuer/task, numeric repository identity, exact derivation/linkage,
and full baseline/accepted/oracle/production-patch/executable-reference artifacts.
Its finite validity window must fit inside the parent's window. Both exact authorization
digests must appear in the unchanged trusted preparation policy's existing allowlist.
This adds no default field to old policies, no second approval system, and no spending
grant. Current preparation and authority must recheck the current policy and both windows.
The content-only validator with `policy=None` validates no issuer or allowlist authority;
it is exclusively for proof reconstruction, never execution or current admission.

The importer checks data bindings and both current rights pins before invoking current
preparation, which remains responsible for the substantive source license, configured
repository/risk/commands, protected paths, exact frozen selectors, original regression
scope and reference reconstruction. Only after these checks does it freeze metadata.
`ImportedHistoricalTaskV2` remains `IMPORTED_NOT_QUALIFIED`, with no execution/admission
capability. No task or executable reference is silently converted to v1 provenance.

Accepted-source exclusion is enforced by the separately versioned qualification-input
resolver: model inputs retain the existing reviewed projection rather than receiving
accepted snapshots or provenance aggregates. Completing import does not establish a
passing twelve-run matrix, calibration, independent review, current qualification,
worker-export/scoring authority, or a historical benchmark result.

## Recorded development evidence

The owned synthetic test run covered 187 cases across v1/v2 import, derived rights,
linkage, derivation and the initial shared resolver; Ruff and mypy passed. It used no
historical payloads or code execution. Subsequent independently reviewed owned tests
cover shared projection, current-title exclusion, outer checkpoints and the full
controlled controller/admission/resume path, including cancellation at the shorter
derived expiration. These later checks are separate from that earlier 187-case run;
see [derived inputs](derived-qualification-inputs.md) for their scope.

Separately, after the reviewed linkage implementation, a protected capture for
`dbader/schedule` PR 463 and issue 175 used two fixed metadata-only GraphQL queries:
2,646 response bytes, with no issue text, accepted code, author names or model calls.
Both responses agreed. Validation matched the accepted commit to the acquired tree
and sole baseline parent, the merged PR to the issue's closing event, and the required
pre-commit requirements/merge/capture chronology. Full trees, derived tests and
requirements remained in protected storage; see the retained
[development observations](historical-reference-derivation.md#subsequent-protected-development-observations).

This capture grants no processing rights and imports no task. There are still zero
actual historical imports or qualifications from these observations. Current data
authorization, runtime and independent qualification gates remain open.
