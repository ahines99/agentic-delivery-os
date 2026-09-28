# Local operations and recovery

Run control-plane processes as a dedicated operator. Target code runs only through the fixed
Docker runner. Never mount the Docker socket into the HTTP API or a target job.

## Start a reproducible local environment

```sh
uv sync --locked --extra dev
uv run python scripts/configure_local.py
docker compose --env-file .local/compose.env up -d --wait
uv run delivery-service migrate --config config.local.json
docker build -t agentic-delivery-sandbox:dev -f infra/docker/sandbox.Dockerfile infra/docker
docker image inspect agentic-delivery-sandbox:dev --format '{{.Id}}'
```

The configure script refuses to overwrite existing private configuration. Copy the inspected
immutable image ID into the repository's `sandbox_image`. Supply an authorized model configuration
and current recorded rates before enabling `model_data_authorized`. Set its API key in the worker's
environment; do not put it in the JSON settings, ticket, or target files. Keep local secret files
owner-readable and outside synchronization/publication. The generated bearer credential is in
`.local/operator-token`; only its SHA-256 is in configuration.

The configure script uses the account's existing filesystem permissions; it does not harden
Windows ACLs. Use a private operator-owned directory. On Unix, run configuration with `umask 077`
and restrict existing `config.local.json`, `.local/operator-token`, `.local/postgres-password` and
`.local/compose.env` to owner access. On Windows, inspect and restrict those files' Security
permissions to the operator and required system administrators. The JSON configuration contains
the database credential; an ignored filename does not protect it from other local users.

Start each process in its own terminal with the project working directory:

```sh
uv run uvicorn agentic_delivery.api.app:app --host 127.0.0.1 --port 8000
uv run delivery-service worker --config config.local.json
uv run delivery-service dispatch --config config.local.json
```

The API loads `config.local.json`, or the path in `DELIVERY_CONFIG`. The database and Temporal
listen on localhost ports 25432 and 27233. This development Temporal server is not production
infrastructure. The Compose network is a private project bridge with loopback port publication;
target jobs separately use `--network none`. Stop this project's services with
`docker compose --env-file .local/compose.env down`; volumes remain for recovery.

## Intake, decisions and evidence

Use `Authorization: Bearer <local credential>` on all `/work-items`, `/workflows` and `/commands`
requests. `POST /work-items` requires a unique `Idempotency-Key` and a WorkItem body. A 202 means
durable receipt, not completed work. Query the returned workflow/command IDs. The operator must
have access to the configured repository and the operator role for writes.
Resubmitting the same source ticket with a changed payload returns 409 rather than creating a
parallel attempt with a new budget; use the supported clarification or rerun lifecycle.

At `PLAN_REVIEW`, submit `/workflows/{id}/approve-plan` with the current `expected_sequence`,
`spec_digest` and `plan_digest`, plus a new idempotency key. A stale tuple is rejected by Temporal.
Approval additionally requires the `reviewer` role. The human-decision deadline is absolute;
invalid or repeated commands cannot extend the wait. Signals resolve the canonical stored command
and current actor authorization before application; sending a command-shaped signal is not approval.
Clarification uses `/workflows/{id}/clarify` with the sequence, digest and replacement `item` while
waiting for clarification. Cancellation uses `/workflows/{id}/cancel` with sequence/digest.
Inspect command disposition after dispatch; queued does not mean applied.

For an eligible `FAILED`, `CANCELLED` or `POLICY_BLOCKED` attempt, submit
`POST /workflows/{id}/rerun` with exactly `expected_sequence` and `spec_digest`, operator
authentication and a new idempotency key. This creates a separate linked attempt and budget;
the previous attempt's spend and history remain intact. Existing or uncertain publication outcomes
must be reconciled first and block rerun. It does not reopen a terminal workflow or automatically
continue a half-finished build.

Each run pins an execution-configuration digest, including model, repository, budgets and
publication settings. Changing that configuration invalidates continuation; use a new eligible
attempt with a fresh plan and approval. Do not enable publication mid-run to bypass a disabled
publication decision.

`GET /healthz` is process liveness. `GET /readyz` verifies database/schema access and returns
503 when unavailable; it does not probe Temporal, Docker or model providers. Authenticated
`GET /operations` reports only repositories visible to the operator, including state counts,
spending and pending/exhausted dispatch summaries. These are local operational views, not a
complete production telemetry/export system.

Evidence metadata is in the workflow result. Bytes live in the configured artifact store under
their content digest. Read with `ArtifactStore.get`, which verifies the hash. Keep an access-controlled
copy of the manifest, candidate/diff and command receipts when sharing a demonstration. Artifact
hashes establish identity, not test adequacy or absence of defects.

## Incidents

| Incident | Operator action |
| --- | --- |
| Pause new work | Set `admissions_enabled=false` and restart API; cancel active work through authenticated commands. |
| API/dispatcher restart | Restart process with same settings/database. Inbox/outbox leases recover; do not delete rows or create replacement IDs. |
| Worker restart during human wait | Restart worker on same task queue. Temporal restores state from history; retain the same workflow code version or replay before upgrade. |
| Provider timeout or missing usage | Preserve the RESERVED usage entry; reconcile billing and provider request identity. Do not retry generation under a new operation ID to bypass budget. |
| Publication response lost | Reconcile `agent/{workflow_id}` branch, exact tree/commit marker and PR before retry. The final PR must still have the exact base/head, repositories, refs, open state and draft status. Uncertain publication blocks rerun; never force-push to repair uncertainty. |
| New base/head after verification | Treat evidence as stale; do not merge based on old checks. Start a separately reviewed attempt after revalidation. |
| Sandbox cleanup failure | Find only containers with `agentic-delivery.managed=true`; inspect recorded run identity, then remove that confirmed job. Never prune shared Docker resources. |
| Key exposure/revocation | Pause admission, revoke the affected provider/operator credential, rotate configuration and restart trusted services; never inject replacement credentials into jobs. |
| Database recovery | Restore a consistent database backup and retained artifact store together; reconcile with Temporal and provider state before resuming dispatch. Automated reconciliation/restore drills are still a release gate. |

Do not manually rewrite audit history or workflow states. Use the explicit rerun endpoint rather
than resetting state or spending. Granular build recovery, production retention/deletion and
cross-system recovery drills remain recorded gaps in
[implementation status](implementation-status.md).

## Validate

Run lint, format, types and tests as in the README. Integration tests require
`TEST_DATABASE_URL`, `TEST_TEMPORAL_ADDRESS` and `TEST_SANDBOX_IMAGE`; unconfigured tests report
explicit skips. The latest local run passed 163 tests with all three configured against actual
Compose PostgreSQL/Temporal and Docker, including memory/PID/disk limits and hostile PEP 517 hooks.
Hosted CI passed on Python 3.12/3.13 and disposable PostgreSQL/Temporal/Docker services without
provider credentials, plus secret scanning. Check the PR's current revision before merging.
The two `scripts/live_*_check.py` scripts are operator-invoked development checks that spend model
tokens; they require explicit environment-file and image inputs and were exercised against the
recorded local services. They are not an unattended benchmark campaign.

For offline evaluation tooling, `uv run delivery-eval --help` lists schema export, manifest
validation and deterministic reporting. Follow [evals/README.md](../evals/README.md); structural
validation does not verify artifact provenance or human qualification of historical tasks.

The [local backup drill](local-backup.md) was exercised against the Compose database and artifacts.
Stop all writers before invoking it; the script only restores into a newly created disposable
database. It does not restore Temporal or provider state. Follow [provider onboarding](provider-onboarding.md)
to supply the live integration inputs and keep publication disabled until they are verified.
