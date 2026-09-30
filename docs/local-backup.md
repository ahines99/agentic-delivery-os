# Local backup and disposable restore drill

`scripts/backup_local.py` verifies a development PostgreSQL dump and a digest-checked copy
of local artifacts. It does not restore the source database, Temporal history, provider
state, credentials, or worker configuration, and does not resume a workflow.

## Run while writers are stopped

Stop the API, worker, dispatcher, live runs, integration tests, and any other database or
artifact writers. Leave this project's PostgreSQL container running. The flag below records
the operator's confirmation; the script cannot establish quiescence automatically.

```powershell
.venv/Scripts/python.exe scripts/backup_local.py --quiescent
```

For the installed live service, select its database explicitly:

```powershell
.venv/Scripts/python.exe scripts/backup_local.py --quiescent --database delivery_live --artifact-root .local/artifacts
```

Use the database name and artifact directory from the intended local configuration.
The database must be `delivery` or a `delivery_`-prefixed name; system databases and
disposable restore names are rejected. The artifact source must resolve beneath this
workspace's `.local`, outside `.local/backups`. The manifest records both selected
sources. These arguments select data in the verified local Compose container; they
do not connect to a remote database. Stop the login supervisor as well as its child
service processes during the drill, then restart the scheduled task afterward.

The script resolves exactly one running container labelled Compose project `agentic-delivery`
and service `postgres`, inspects those labels and its running state, and uses the resulting
full container ID for every operation. It uses `docker exec` and the existing local PostgreSQL
role `delivery`; no password, connection URL, or container environment is printed.

It creates a unique directory under ignored `.local/backups/` containing:

- `delivery.pgdump`, a PostgreSQL custom-format dump of the selected database (`delivery` by default).
- `artifacts/`, with source and copied bytes checked against their content-addressed digests.
- `manifest.json`, recording SHA-256 values, byte counts, artifact inventory, public-table
  row counts, Alembic revisions, container identity, and the drill result.

The dump is capped at 64 MiB; copied artifacts at 10,000 files and 256 MiB total, with the
artifact store's existing 4 MiB per-file cap. Each child command has a 90-second deadline.
Unexpected artifact files, links/junctions, digest mismatches, or changed source counts cause
failure. Partial backups remain with a failed manifest and must not be treated as verified.
Backups can contain private source and issue data: keep `.local` owner-restricted and out of
Git, synchronization, logs, and publication. The script neither encrypts nor uploads backups.

## What restore verification does

The script generates a strict `delivery_restore_<32 lowercase hex characters>` database name
and verifies that it does not already exist. Only after successful creation does it restore
the dump into that new database. It compares all public-table row counts and Alembic revisions
with the source fingerprint, then drops exactly that newly created database, including on a
restore/verification failure. It confirms the disposable database no longer exists.

It has no option to restore into an existing database or remove Docker resources. If creation
returns an unknown outcome, the script does not guess ownership and drop a database. An
operator must inspect that exceptional case. If Docker or PostgreSQL becomes unavailable
during cleanup, the drill fails; exact disposable-database cleanup may require operator work.

## Interpretation

`VERIFIED_LOCAL_DRILL` establishes that the captured dump could be restored into a disposable
database with matching table counts/revisions, and that the artifact copy matched its digests.
Counts do not prove row-by-row equality or cross-system consistency, and pre/post count checks
cannot detect every concurrent update. The explicit quiescence requirement remains necessary.

Temporal history, credential/configuration recovery, provider-side reconciliation, recovery
point/time objectives, off-host durability, encryption, and production recovery remain separate
release gates. Never start workers against the disposable database or use this drill as an
automatic restore/resume command. The retained manifest describes one local exercise only.

## Recorded local exercise

The drill passed on 2026-09-28 at 03:48 UTC (2026-09-27 local time) against the verified
Compose PostgreSQL container. It retained a 49,191-byte custom dump and 26 artifacts totaling
71,050 bytes. The disposable restore matched all 10 public-table counts and Alembic revision
`0004`, then the disposable database was removed and its absence verified.

The local evidence directory is
`.local/backups/20260928T034856Z-c229c0cc832c4234b7114ce5d1b688fa/`.
Dump SHA-256: `7adfae557696c2f4845ca9eceb017878a508a520c1d2f5c8748511d0848eccab`.
These counts describe that capture; subsequent development runs change the source database.

## Installed live database exercise

On 2026-09-30 at 14:05 UTC, the updated script backed up `delivery_live` and
`.local/artifacts`. All nine workflows were terminal before the supervised service
was stopped; a database check found no other sessions before the drill. The dump
contained 103,687 bytes, and 347 artifacts totaled 1,280,975 bytes. Disposable restore
matched all 12 public-table counts and schema revision `0006`; the created database
was removed and its absence verified. The source database was not restored or changed.
Afterward the login task restarted, API/database readiness returned, and the configured
Linear cursor advanced. The focused backup suite passed 25 tests, including custom
source selection, invalid source rejection and exact disposable cleanup.

Private evidence: `.local/backups/20260930T140517Z-6b39346a1b3e459f964521d7bfe75a13/`.
Dump SHA-256: `db8ef1d3d30b3b2ebc39a8a4752d3d3c9d2e1a913ea7f326b9c5541d223ac88b`.
This remains a database/artifact drill; Temporal and provider recovery are separate.
