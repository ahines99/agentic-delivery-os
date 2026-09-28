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
commit-only closers, merge commits with multiple parents, redirects represented as
changed identities, or inconsistent captures are unsupported and refuse the profile.

Acceptance time is the PR's `mergedAt`. The commit's `committedDate` must be no later,
but is not substituted for acceptance time. Requirements creation/edit time must precede
acceptance, the closing event must be no earlier than merge, and all capture times must
be no later than current trusted time. Full baseline/accepted acquisitions are read and
reconstructed through the derivation; neither snapshot capture alone asserts a parent
or acceptance timestamp.

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
