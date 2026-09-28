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

The script resolves exactly one running container labelled Compose project `agentic-delivery`
and service `postgres`, inspects those labels and its running state, and uses the resulting
full container ID for every operation. It uses `docker exec` and the existing local PostgreSQL
role `delivery`; no password, connection URL, or container environment is printed.

It creates a unique directory under ignored `.local/backups/` containing:

- `delivery.pgdump`, a PostgreSQL custom-format dump of database `delivery`.
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
