# Read-only artifact retention planning

The local control plane can produce a conservative, metadata-only retention plan.
It cannot delete artifacts, and `CANDIDATE_REVIEW_ONLY` is never deletion authority.
This is partial M4 operations work; retention enforcement, coordinated deletion,
legal-hold discovery, and complete provider/Temporal recovery remain open.

## Required scope

Use a dedicated control-plane content-addressed artifact directory. Stop all writers
and verify their work is settled before planning. The planner also refuses active or
human-review workflows, unsettled model reservations, undelivered outbox rows,
pending commands, unknown operation outcomes, and publications that are not closed
or merged. A terminal workflow alone does not establish quiescence.

Four explicit assertions are required: the store is dedicated to this control plane;
writers are quiescent; external references and retention/legal holds have been
accounted for; and backups are independent of the scanned files. These are operator
assertions, not discoveries or attestations made by the planner. A shared evaluator,
import, or other application store cannot be called dedicated merely because its
files have SHA-256 names. Establish a separate scope or refuse planning. Express all
retained external/hold roots with `--retained-root`; every supplied root must exist.
Backups must have independent bytes and manifests outside this store, not hardlinks
to candidate files. Their creation, validity, ownership, and retention are not inferred.

## Run

With those facts established, choose an explicit age policy and a new JSON output
outside every configured repository and artifact store. Create a private output directory
first (the tool will not create it), for example `C:/private/delivery-exports`. Then run:

```powershell
python -m agentic_delivery.operations.retention --config config.local.json --output C:/private/delivery-exports/retention-review.json --retention-days 90 --dedicated-control-plane-store --writers-quiescent --external-roots-complete --backups-independent
```

Add `--retained-root <sha256>` for each external root. The CLI refuses overwrite,
protected source/configuration/artifact destinations, missing scope assertions, and
uncertain evidence. Errors are sanitized; privately investigate the input rather than
publishing database exceptions or credentials. This command never migrates or writes
the database, changes provider state, deletes files, or resolves unsettled workflows.

## How the plan is bound

PostgreSQL reads use a read-only, repeatable-read transaction. SQLite uses a read-only
URI and an explicit transaction. The planner reads every field of every known schema
table, bounds rows/bytes, and rejects unknown/missing tables or changed columns. It
hashes the complete private snapshot, including migration versions, into a database
watermark. All digest-shaped values conservatively contribute possible roots.

The artifact inventory permits only regular, single-link files at canonical
`<two hex characters>/<64 hex characters>` paths. Symlinks, junctions, hardlinks,
temporary files, other directory layouts, and special files are refused. Reads are
bounded and hash verified. UTF-8 text and decoded JSON are scanned for SHA-256-shaped
references, including recursively decoded JSON string values such as a snapshot's
embedded metadata file. Duplicate JSON keys are rejected at every decoded layer,
including escaped aliases of a key; no overwritten value can silently lose a reference.
Malformed structured text, ambiguous nested JSON and opaque binary files refuse the whole plan.
This deliberately over-retains ordinary digest-shaped values. Hashes that do not
identify a present artifact may represent policy, content, or other hashes and do not
create a file; this is not an artifact-completeness validator.

Database roots, explicit roots, files at or newer than the cutoff, and future-dated
files are kept. Their transitive references are kept too, including references from
young files to old dependencies. Only an older file without a retained reference is
classified as a review candidate. File modification time is an age input, not proof
of creation time or last use. Metadata changes are checked around reads; a second
inventory and second database snapshot must match before the report is produced.

The report contains digests, byte counts, modification timestamps, dispositions and
reason codes. It excludes database payloads, source/test bytes, tickets, actor names,
provider responses, filesystem paths, and credentials. It binds the configuration,
database watermark, artifact listing, reference graph, cutoff and assertions into a
plan digest. It is private operational metadata, not a benchmark or readiness result.

Limits are 10,000 artifact files, 4 MiB per file, 256 MiB total artifact bytes,
10,000 rows per database table, and 64 MiB of encoded database rows. Each reference scan
also permits at most 32 traversal levels, 100,000 visited values and 16 MiB of cumulative
decoded text. Exceeding any limit refuses the plan instead of silently truncating it.

## Evidence and remaining boundary

On 2026-09-28, the focused tests exercised SQLite read-only planning, database and
transitive roots, escaped JSON references, exact age boundaries, external holds,
active/unknown work, corruption, hardlinks, scope and size limits, concurrent changes,
and exclusive metadata output. A real PostgreSQL integration test created a unique
`delivery_retention_<random>` database and synthetic store, verified both snapshot
transactions were read-only/repeatable-read, kept a database root and its child,
classified one old unrelated file for review, and verified unchanged workflow and
artifact bytes. Only the newly created disposable database was dropped; its absence
was checked. The shared workflow database and actual artifacts were not modified.
Unprivileged symlink creation and POSIX FIFO cases are explicitly skipped on this
Windows host; the FIFO test runs in a bounded subprocess on POSIX.

Independent review then reproduced a missed escaped reference inside nested JSON and a
duplicate-key overwrite. Regression tests now require transitive retention through multiple
encoded layers, refusal of duplicate/escaped-equivalent keys, and fail-closed parsing limits.
These corrections do not add deletion authority or establish semantic reference completeness
for arbitrary encodings; unsupported or uncertain structured inputs remain refusal cases.

The two snapshots detect observed changes but are not a writer lock and cannot prevent
a race after the last check. An unreferenced file can still have an unobserved external
consumer. No deletion API is provided until writer coordination, complete external
roots/holds, independent backups, and a fresh transactional deletion design are
established. Do not turn this report into an unattended filesystem deletion script.
