# Bounded operational metadata export

The offline exporter creates one schema-versioned JSON report for an existing workflow. It
provides M4-03 operational evidence without exporting source trees, ticket bodies, model output,
command output or private configuration. It does not contact Temporal, GitHub, Linear or a model,
and does not delete, repair, archive or expire records.

## Run locally

Create a private destination directory outside configured target repositories and artifact stores,
then choose a new `.json` filename:

```sh
uv run python -m agentic_delivery.operations.export --config config.local.json --workflow-id WORKFLOW_UUID --output /private/delivery-exports/workflow-report.json
```

On Windows, use a quoted local path such as `"D:\Private Exports\workflow-report.json"`.
The parent directory must already exist. The command refuses existing files, configuration
filenames, artifact directories, project source/documentation/test directories, configured local
target repositories, network paths, and paths through symlinks or junctions. Exclusive file creation
also prevents another exporter from replacing the destination between validation and opening.
Use a trusted operator-owned directory; the tool does not defend against its owner maliciously
changing directory structure during export.

The CLI assumes a trusted local operator authorized to read the supplied configuration/database.
It does not authenticate a bearer token or provide a remote download endpoint. The workflow's
repository must be onboarded in that configuration. Protect configuration and directory permissions
as described in the [runbook](runbook.md); Unix exports are created with mode `0600`, while Windows
file access follows the destination directory's ACL. Do not treat local filesystem access as a
production multi-tenant authorization design.

Success prints only the export status, schema version and SHA-256 of the output bytes. Errors are
sanitized and exit with code 2, without echoing credentials, private configuration or malformed
workflow input. The tool never overwrites an old export. A filesystem failure after file creation
can leave a partial file; it is not reported as successful and is not automatically deleted.

## Schema version 1

| Section | Allowlisted metadata |
| --- | --- |
| `workflow` | Workflow UUID, repository, state/sequence, specification and execution-configuration digests, timestamps, model spend/reservation and token-count totals, selected manifest/CI evidence digests |
| `transitions` | Event ID, sequence, previous/next state, event digest and timestamp |
| `command_dispositions` | Command ID, operation kind, disposition and timestamp |
| `model_operations` | Application-generated operation ID, reservation/settlement status, reserved/actual microdollars and reserved token counts |
| `publication` | PR number, base/head SHAs, manifest digest, observed status and timestamp |
| `ci` | Configured repository ID, head SHA, generation/watermark, policy/evidence digests and reconciliation/expiry timestamps; explicitly observational |

Each report includes `schema_version`, report kind, export time and the **exporter's** policy
version. The latter is not an assertion about historical policy. Stored configuration/CI policy
digests provide their own version binding. Empty or malformed digest fields become null rather
than exporting arbitrary strings. No artifact bytes are read or bundled: exported digests identify
references only and do not prove that an artifact exists or is authentic.

An unsettled `RESERVED` model operation is explicitly `outcome: UNKNOWN`, with its reserved amount
retained and actual spend left unknown. It must not be counted as zero cost or a failed operation
that can be freely retried. `unknown_model_operations` makes this uncertainty visible. A `SETTLED`
operation records its settled cost; it does not mean the candidate or delivery succeeded.
Only known application-generated plan/build/review operation-ID formats are included verbatim;
unsupported identifiers are null. Workflow and command IDs still support local correlation.

Actor names, approval/authentication hashes, idempotency keys, request and provider payloads,
ticket title/description, prompts, generated source, stdout/stderr, free-text reasons/errors,
provider response IDs, secret values, database URLs and credential environment-variable names
are excluded. CI check output and snapshot payloads are excluded. Repository identifiers and
timestamps remain potentially private metadata, so sharing an export is still an operator decision.

## Consistency and limits

SQLite is opened in read-only mode inside an explicit read transaction. PostgreSQL uses a
read-only repeatable-read transaction. No migrations or provider reconciliation run during export.
Every list has a 10,000-row ceiling; exceeding it rejects the report instead of silently truncating.
The exporter can be used on active workflows, but its contents describe a database snapshot and
can immediately become stale. It does not declare readiness from an unexpired CI cache.

This report is not a backup, retention/deletion implementation, metrics service, tamper-proof audit,
human qualification, or complete benchmark provenance. Missing publication/CI sections remain null.
For actual provider state, use reconciliation; for historical evaluation, use the separate
[evaluation protocol](evaluation-methodology.md).

## Verification

```sh
uv run python -m pytest tests/test_operations_export.py -q
```

SQLite tests seed secret canaries into ticket bodies, actors, idempotency keys, free-text reasons,
model/provider responses, publication details and CI payloads. The exported JSON excludes those
canaries while retaining digest references, correlation fields and explicit unknown reservations.
Tests also cover workflow isolation, exclusive creation, protected destinations and sanitized
failure output. Symlink tests run where the operating system permits unprivileged link creation;
otherwise that specific case reports an explicit skip. No real provider calls or paid model runs
are involved.
