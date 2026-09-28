# Validation-only qualification preparation

`evaluation/qualification_preparation.py` implements a pure preparation gate for the
existing automated qualification protocol. It reads already imported protected artifacts,
checks a pending task against trusted operator configuration, and proves that the supplied
text patch reconstructs the declared reference snapshot. It writes no files, exports no
source or oracle, runs no commands, invokes no model, and admits no task.

## API and producer boundary

```python
prepared = prepare_qualification(
    request,
    settings=settings,
    policy=policy,
    protected_artifacts=protected_store,
    output_root=existing_evaluator_output_directory,
    worker_root=existing_worker_directory,
    now=controller_utc_time,
)
```

The request names three immutable artifacts: a normalized `HistoricalTask` draft,
the existing `Provenance` record, and `ReferenceProvenance`. The controller reserves exactly
two reviewer context IDs before preparing the draft. Its `qualification_mode` is
`independent-agents-v1` and its pending `qualification_artifact` is 64 zeroes. Selecting
that mode does not grant admission: `HistoricalTask.worker_input()` still requires a real
validated qualification record. Reserving these fields now keeps the manifest digest stable
when the actual qualification artifact is attached later; only that artifact field is excluded
from `qualification_task_digest`.

Trusted caller inputs are separate from submitted artifacts:

| Input | Required binding and producer responsibility |
| --- | --- |
| `Settings` | Onboarded repository identity, pinned image, exact approved command profiles, model-data authorization, budget ceilings, policy and protected paths. Disabled admissions fail closed. |
| `PreparationPolicy` | Current policy version, authorized attestation issuer IDs and exact approved authorization-artifact digests. The controller supplies this policy; submitted content and agents cannot grant themselves authority. |
| `LicenseEvidence` | Repository/base, source snapshot, allowlisted license label, actual source license-file path/hash and immutable GitHub blob URL. The source text must be substantive; arbitrary nonempty evidence blobs fail schema validation. |
| `UsageAuthorization` | Typed controller attestation, approved issuer/digest, exact task/repository/base/source revision/issue/license evidence/scope, issuance and expiry times. |
| `ReferenceProvenance` | Exact task/base/source/oracle/patch/reference bindings, a distinct claimed accepted historical commit and its exact repository commit URL. |

These records are **trusted-controller attestations and imported identity claims**. Content
hashes, an 80-character minimum license text and a typed authorization record do not establish
legal clearance, authenticate an arbitrary writer, verify historical acceptance or chronology,
or prove that a claimed source tree came from GitHub. The importer and configured controller
must supply genuine evidence before actual execution; this module does not fetch it. Staged
metadata-only candidates and earlier incomplete synthetic qualification fixtures are not
automatically usable preparation inputs.

## Offline CLI

The CLI exposes the same validation-only gate and writes one new metadata summary:

```text
delivery-eval prepare-qualification --config /private/config.json --request /private/request.json --policy /private/preparation-policy.json --artifacts /private/protected-artifacts --output-artifacts /private/evaluator-results --worker-root /private/worker --output /private/reports/preparation.json
```

The request and trusted policy are strict JSON documents matching `PreparationRequest` and
`PreparationPolicy`. Export their schemas with `delivery-eval schema --kind preparation-request`
or `--kind preparation-policy`, followed by `--output`. `license-evidence`, `usage-authorization`
and `reference-provenance` schemas describe the referenced records. Schema export supplies no
authority and creates no provenance evidence.

All three scope directories and the output parent must already exist. The summary must be
outside the input/output artifact stores, worker root, configured repositories and protected
configuration/source paths. Existing output is never replaced. Inputs are bounded regular local
files; links, duplicate JSON keys and nonfinite values are rejected. The command uses current UTC
time rather than a caller-supplied eligibility clock. Its errors are sanitized so private
validation content is not printed. No credentials are loaded, no ledger is opened, and no task
code, Docker workload or model is executed.

The function itself remains read-only; only the CLI's explicitly selected new summary is written.
Tests exercise the real preparation gate with synthetic records, output/input protection,
missing-scope refusal without directory creation, private-error suppression and no-execution
spies. The FIFO refusal case runs on POSIX and explicitly skips on Windows.

## Reference patch proof

The parser applies patches to the immutable source mapping in memory. It accepts only UTF-8,
LF-terminated unified text diffs with `--- a/path` / `+++ b/path` headers and exact hunk
coordinates, counts and context. Creation/deletion must use `/dev/null` on the absent side.
Multiple files and multiple hunks are supported. Patched nonempty files require a final LF.
There is no shell, Git invocation, fuzzy matching, offset correction or path traversal.

Git preambles/index metadata, quoted or timestamped paths, renames, binary patches, mode
changes, CRLF patch lines, no-final-newline markers, duplicate file sections and no-op files
are rejected. Unsupported historical patches require a separately reviewed deterministic
import normalization with retained provenance; this gate does not strip information itself.

Limits are 1 MiB of patch text, 50 changed files, 1,000 hunks, 240 characters per patch path,
4 MiB per JSON artifact, and the existing snapshot limits of 1,000 files, 256 KiB per file
and 8 MiB combined content. JSON duplicate keys, nonfinite values, invalid UTF-8, NUL file
content, case aliases and file/directory collisions fail closed. Snapshot artifacts also remain
subject to their `ArtifactStore` read limit.

The source and oracle must be disjoint. This bounded profile accepts oracle Python test files
without runner/control overrides. After patch application, adding the unchanged oracle must
produce the exact declared reference mapping. Existing conventional test paths, explicit
regression selector paths, the source license, configured protected paths and shared execution
control/dependency paths cannot change. Changed code also passes the existing conservative
low-risk checks. Those checks do not establish general code safety or semantic correctness.

## Output and next execution gate

Protected input storage, evaluator output storage and the worker directory must already exist
and be pairwise disjoint, including either direction of nesting. Linked scope paths are
rejected. A configured local repository is also checked against both stores. The output
directory is checked but never written. A successful result contains only task/request IDs,
digests, policy/configuration bindings and the controller timestamp, with explicit
`PREPARED_NOT_QUALIFIED`, `admitted=false` and `execution_authorized=false` fields. Python syntax
failures are sanitized so exception text does not expose protected reference code.

Both stores remain evaluator-only: their underlying imported material must never become model
context merely because the result contains a digest. Preparation does not prove semantic
nonleakage of task descriptions, filesystem confidentiality, or protection against a concurrent
privileged filesystem replacement. The future execution controller must revalidate the current
policy, authorization expiry, filesystem scopes and immutable artifacts before effects; reserve
and account for actual costs; run the twelve baseline/reference checks; execute calibrated,
independent agent reviews; and call the existing admission validator. Prepared metadata cannot
replace any of those gates or authorize sealed-test access or spending.

The focused tests use explicitly synthetic source, references, identity claims and controller
attestations. They exercise actual parsing, hashing, configuration, artifact and filesystem
validation; they are not historical qualification runs or legal evidence. No held-out answers
or paid providers are required to run them.
