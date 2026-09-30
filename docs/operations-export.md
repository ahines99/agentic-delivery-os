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

## Optional lifecycle metrics (schema version 2)

Add `--include-metrics` to the same command to include a `metrics` object and emit
schema version 2. The default remains version 1. This reads the same database
snapshot; it adds no telemetry service, provider requests or model charges.

The exporter checks contiguous legal transitions, projection agreement, timestamp
ordering, command identities, model operation identities and accounting totals
before deriving measurements. An inconsistent snapshot fails the export before
creating its output file. Measurements include:

- Milliseconds per workflow state, initial queue time, total lifecycle time, and
  combined plan-review/clarification wait. These use projection commit timestamps,
  with each interval rounded down to milliseconds. They are not exact worker CPU
  or execution times. Active workflows age to the snapshot time; terminal workflows
  stop at their terminal transition, including `HUMAN_REVIEW`.
- Clarification entries and applied cancellation commands. An applied cancellation
  request does not establish successful cancellation or sandbox cleanup.
- Reserved repair model operations with known `build:N` identities where N is
  greater than zero. This counts model operations, not successful corrections.
  `model_role_counts_complete: false` identifies missing role classification; the
  reported count then covers only recognized identities. Unclassified operations
  still contribute their recorded costs and reservations.
- Recorded settled model cost, unsettled reservations and unknown-operation count.
  `cost_to_recorded_handoff_microdollars` is populated only for `HUMAN_REVIEW` with
  all recorded operations settled. It is not cost per human-accepted change and
  excludes infrastructure costs. Unknown costs remain unknown.

The `unmeasured` list explicitly retains manual-acceptance wait, external human
review latency/benefit, false-ready rate, duplicate suppression, cleanup failures,
provider error counts and infrastructure cost. `ACCEPTANCE_CHECK` can include CI
and manual review, so its total duration cannot identify the manual portion.
These measurements describe recorded history, not current provider readiness or
historical evaluation results.

Manual-review command dispositions are supported in both report versions. Their
private decisions, comments and evidence payloads remain excluded.

### Recorded provider and cleanup observations

This extension is newer than installed `4ae54e6` and is not installed yet.

Version 2 also derives `model_provider_observations` and
`candidate_cleanup_observation` inside the same read-only transaction. The queries
select fixed JSON scalars, without retrieving model output, provider response IDs,
returned model names, exception text or cleanup payloads. Version 1 is unchanged.

Model counts distinguish recorded HTTP responses other than the adapter's accepted
HTTP 200, transport errors, and local cancellation. `recorded_errors` sums the first
two categories; cancellation stays separate. Each observation must match its stored
workflow/operation identity and supported schema. `missing_observations` and
`coverage_complete` describe coverage of the recorded model operations. Zero recorded
errors with incomplete coverage does not establish an error-free run. These are
model-adapter observations, not counts of GitHub/Linear errors or remote generations.
They never settle usage, release reservations or authorize a retry.

Cleanup reports the observation currently retained in the workflow projection:
`CLEANED` requires `verified_absent: true`; `UNKNOWN` requires false. No observation
becomes `NOT_RECORDED` with a null verification field. UNKNOWN does not establish an
actual cleanup failure, and NOT_RECORDED does not establish successful cleanup.
This is not a total count of all cleanup attempts and performs no cleanup itself.
The broader unmeasured provider/cleanup outcomes remain explicit.

SQLite exposes JSON booleans as integer scalars. The diagnostic query retains the
JSON type so `true` cannot be accepted as schema version `1`, and an integer `1`
cannot become a verified cleanup flag. PostgreSQL retains its native JSON types.
Malformed or contradictory observations fail the version 2 export before output
creation; arbitrary stored strings cannot enter error messages or the report.

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
uv run python -m pytest tests/test_operation_metrics.py -q
```

SQLite tests seed secret canaries into ticket bodies, actors, idempotency keys, free-text reasons,
model/provider responses, publication details and CI payloads. The exported JSON excludes those
canaries while retaining digest references, correlation fields and explicit unknown reservations.
Tests also cover workflow isolation, exclusive creation, protected destinations and sanitized
failure output. Symlink tests run where the operating system permits unprivileged link creation;
otherwise that specific case reports an explicit skip. No real provider calls or paid model runs
are involved.

The metrics tests cover timing, unknown costs, unclassified operations, inconsistent
history/accounting and private-output exclusion. The PostgreSQL integration test
uses a disposable test database, checks actual read-only/repeatable-read transaction
settings, and verifies export leaves the workflow unchanged. It requires
`TEST_DATABASE_URL`; do not point this test at the live database.

The 2026-09-30 focused run passed 34 tests with one Windows symlink skip, including
the actual PostgreSQL case. Ruff, formatting and mypy passed. A separate read-only
measurement of the two existing live demonstration workflows produced:

| Ticket | Recorded lifecycle | Clarification entries | Recorded model cost | Unknown model operations |
| --- | --- | --- | --- | --- |
| PER-13 | 2,219,508 ms | 0 | 215,420 microdollars | 0 |
| PER-14 | 1,764,290 ms | 1 | 259,145 microdollars | 0 |

Both histories end at `HUMAN_REVIEW`, with complete role classification. These are
two individual demonstrations, not benchmark averages or human acceptance evidence.
The exporter was run separately against installed history; no new live delivery
was created by that measurement.

The lifecycle/export source at `d482c5b` subsequently passed
[complete hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36760353617):
3,381 tests and 153 skips on each Python version, all 156 service integration tests,
builds and secret scanning. Lifecycle metrics are now installed through `4ae54e6`
after its own complete CI and [verified idle upgrade](local-runtime-upgrade.md).
The later diagnostic observation extension passed
**55 tests with one Windows symlink skip in 8.78 seconds**, including real
PostgreSQL adapter success, HTTP failure, transport loss and cancellation. Those
tests verify unchanged ledger state, retained unknown reservations, one HTTP
operation and private-canary exclusion. Ruff, format and mypy passed. Its full-source
verification and installation remain pending.
