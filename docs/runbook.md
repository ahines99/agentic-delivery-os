# Local operations and recovery

Run control-plane processes as a dedicated operator. Target code runs only through the fixed
Docker runner. Never mount the Docker socket into the HTTP API or a target job.

## Use the existing installation

The Windows task `AgenticDeliveryOS` supervises the local service. Keep this machine
awake and Docker Desktop running. Its configured target is `agentic-delivery-os`,
base branch `delivery-workbench-v2`, with changes scoped to `demos/sample_repo`.
Create a new Backlog ticket in the Personal Project Portfolio Linear team, leave it
unassigned, include `Repository: agentic-delivery-os`, add the `delivery-ready` label, and describe the required
behavior and acceptance criteria within that scope. Detection runs every 30 seconds.
Ambiguity pauses the workflow; edit the ticket to answer the clarification. A
successful run attaches a tested draft PR and moves the ticket to In Review.
Human review and merge remain separate.

The installed application is `63f25f2`; its hosted checks and supervised restart
passed, including automatic confirmation of an existing publication after worker
failure, correlated-event logging, lifecycle metrics and provider/cleanup diagnostics.
See the [upgrade record](local-runtime-upgrade.md) and [verification status](implementation-status.md)
for exact evidence. GitHub App and Linear credentials are already configured here.
Installing the App on all repositories does not enable additional execution targets;
see [source compatibility](provider-onboarding.md#current-source-and-execution-profile).

These local checks are read-only:

```powershell
Get-ScheduledTask -TaskName AgenticDeliveryOS | Select-Object TaskName, State
Invoke-RestMethod http://127.0.0.1:18090/readyz
```

Readiness checks API/database access; use the authenticated operations view and
worker/monitor observations when diagnosing delivery. Avoid starting a second
foreground supervisor while the Windows task is already running. The following
setup instructions are for a new environment or a deliberately stopped installation.

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

For local use, start the API, worker and dispatcher together from the project directory:

```sh
uv run --env-file .local/linear.env --env-file .local/model.env delivery-service run --config config.local.json
```

This runs the existing services in one foreground process. The API listens on
`127.0.0.1:18090`, matching the [webhook gateway](linear-ingress.md). Ctrl+C stops
the services; a worker/dispatcher failure also stops the API and exits with an error.
Starting the dispatcher can process queued tickets and spend the configured model
budget. Service shutdown is not a workflow cancellation; use the authenticated cancel
command when cancelling a run. The command does not migrate databases, enable
publication or open a public tunnel. With `linear_poll_start` and repository
`automatic_execution` configured, the monitor detects new tickets and approves eligible
low-risk plans under [ADR-025](adr/ADR-025-automatic-linear-delivery.md). Supply the model
key through the environment or an additional `--env-file` passed to `uv run`.
Keep an optional credential-free webhook gateway in its separate process.

Credentials can use a file reference instead of an inline value. For example, put
`GITHUB_APP_PRIVATE_KEY_FILE='C:/path/to/app.private-key.pem'` in the ignored environment
file. The configured secret name with `_FILE` appended is read only when the direct
environment variable is absent. An explicit empty/short direct value still fails.
File content is never included in loading errors; keep the file owner-readable.

For separately managed processes, use the existing commands:

```sh
uv run uvicorn agentic_delivery.api.app:app --host 127.0.0.1 --port 18090 --no-access-log --no-proxy-headers
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
Approval additionally requires the `reviewer` role. Approval use rechecks the current actor's
reviewer/repository authorization and its finite validity (`approval_validity_seconds`, default
24 hours, maximum seven days), alongside input/plan/configuration bindings. Removing that role
or allowing approval to expire blocks further protected work. The human-decision deadline is absolute;
invalid or repeated commands cannot extend the wait. Signals resolve the canonical stored command
and current actor authorization before application; sending a command-shaped signal is not approval.
Clarification uses `/workflows/{id}/clarify` with the sequence, digest and replacement `item` while
waiting for clarification. Cancellation uses `/workflows/{id}/cancel` with sequence/digest.
Inspect command disposition after dispatch; queued does not mean applied.

The service worker rereads the private configuration for authorization decisions. Under
[ADR-008](adr/ADR-008-active-authorization-and-cancellation.md), candidate work checks current
approval/configuration before each new model or verification operation, on a five-second monitor,
and before returning readiness. Invalid or missing configuration stops protected work; changed
storage/routing/artifact roots require restart. Direct embedded `Activities` callers need a
settings provider to observe file changes. API and dispatcher settings remain startup snapshots.
Replace configuration atomically and restart those processes for token/role/admission changes.

An applied cancellation command means the request was issued, not that cleanup succeeded.
The canonical activity-cancellation path reports `CANCELLED` for recognized cancellation;
a concurrent cleanup/activity error yields `FAILED` with cleanup unconfirmed. Inspect both the
terminal state and exact labelled resource absence. [Actual cancellation drills](active-cancellation.md)
cover a running Docker parent/child workload, failed cleanup acknowledgement and expired approval.
They do not establish daemon/host-loss recovery or immediate interruption of a paid provider call.
Preserve unknown usage reservations and observed publication/tracker effects for reconciliation.

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
hashes establish identity, not test adequacy or absence of defects. The strict manifest gate reads
and validates referenced bytes plus input/configuration/plan/candidate/check/reviewer relationships;
a digest string alone cannot satisfy admission.

Rebuild and pin the sandbox after collector changes. Verification uses the image-owned pytest
launcher and bounded structured report, with plugin autoload/configuration controlled by the image.
Missing completion, early process exit, forged stdout, skipped/failing phases or insufficient test
identities fail closed. The collector and candidate share an interpreter; this is not an attestation
against arbitrary monkeypatching or proof that assertions cover the intended behavior.

## CI and draft handoff

Configure each target's numeric GitHub repository/installation IDs and required check names plus
trusted producer App IDs. The product App needs the read permissions/events in
[provider onboarding](provider-onboarding.md). Follow [CI evidence](ci-evidence.md) for the precise
contract. A check with the right name from a different producer is insufficient.

Signed `check_run` and `check_suite` deliveries are durable observations/invalidation signals.
They cannot alone establish readiness. The broker authenticates bounded paginated REST reads,
compares two complete check snapshots, checks suite state and exact open/draft PR identity/ref/base/head,
and saves a generation-bound snapshot valid for at most 60 seconds. Reruns, new observations,
changed policy or publication context invalidate prior readiness. GitHub propagation and events
in flight leave a residual race; these checks do not replace protected branches and human review.

`GET /workflows/{id}/checks` requires repository-scoped bearer access. `observed_ready` is provisional;
`ci_ready` describes a current reconciled CI snapshot; `ready` additionally requires the current
human-review/handoff context and authorization. The response is observational, never merge authority.
Workflow CI polling defaults to a 900-second absolute deadline and 15-second interval, with configured
maxima of 3600 and 60 seconds respectively. Missing or failing checks cannot become a timeout success.
Cancellation remains available during this wait. Linear review-state update is a separate activity
after the CI gate, with intent/result artifacts and authorization checks before and after its effect.
A lost/failed provider response is UNKNOWN, not an inferred completed handoff. Inspect the publication,
workflow result and retained intent/result before deciding how to reconcile; do not force state rows.

## Incidents

| Incident | Operator action |
| --- | --- |
| Pause new work | Set `admissions_enabled=false` and restart API; cancel active work through authenticated commands. |
| API/dispatcher restart | Restart process with same settings/database. Inbox/outbox leases recover; do not delete rows or create replacement IDs. |
| Worker restart during human wait | Restart worker on same task queue. Replay the [saved prior-commit corpus](versioned-replay.md) before changing workflow code; its synthetic scenarios do not substitute for a supervised version-transition drill. |
| Provider timeout or missing usage | Preserve the RESERVED usage entry; reconcile billing and provider request identity. Do not retry generation under a new operation ID to bypass budget. |
| Publication response lost | Reconcile `agent/{workflow_id}` branch, exact tree/commit marker and PR before retry. The final PR must still have the exact base/head, repositories, refs, open state and draft status. Uncertain publication blocks rerun; never force-push to repair uncertainty. |
| New base/head after verification | Treat evidence as stale; do not merge based on old checks. Start a separately reviewed attempt after revalidation. |
| Sandbox cleanup failure | Find only containers with `agentic-delivery.managed=true`; inspect recorded run identity, then remove that confirmed job. Never prune shared Docker resources. |
| Key exposure/revocation | Pause admission, revoke the affected credential, replace private configuration atomically and restart all consumers requiring startup settings. Verify old-token rejection and new scoped access through the actual ingress. See the bounded [operator rotation rehearsal](operator-rotation.md); provider/replica rotation needs separate evidence. |
| Active authorization loss or cleanup uncertainty | Inspect FAILED outcome, canonical command disposition, retained usage/effect records and exact workflow-labelled resources. Do not relabel failure as CANCELLED or issue a fresh paid operation to hide an unknown outcome. |
| Closed workflow projection damage | Use the preview/apply procedure in [projection recovery](projection-recovery.md). It requires complete closed Temporal history and refuses contradictory audits or concurrent projection changes. |
| Database recovery | Preserve a consistent database/artifact backup; follow the bounded [local restore drill](local-backup.md). Whole-system Temporal/provider reconciliation before resuming dispatch remains a release gate. |
| CI remains pending or changes | Inspect authorized check readiness and producer/ref identity; reconcile through the broker. Never synthesize success or extend the workflow deadline by sending invalid commands. |
| Linear handoff outcome unknown | Preserve intent/result artifacts; inspect the actual issue state and identity before any retry. CI readiness alone does not prove the tracker update happened. |
| Development run remains NEW | Inspect pending/exhausted outbox and configuration digest before retrying. The live development driver scopes dispatch to its workflow so older unrelated rows cannot consume its 20-row claim batch; do not delete unrelated commands. |

Do not manually rewrite audit history or workflow states. Use the explicit rerun endpoint rather
than resetting state or spending. Granular crash recovery, coordinated production deletion and
cross-system recovery drills remain recorded gaps in
[implementation status](implementation-status.md).

## Validate

Run lint, format, types and tests as in the README. Integration tests require
`TEST_DATABASE_URL`, `TEST_TEMPORAL_ADDRESS` and `TEST_SANDBOX_IMAGE`; unconfigured tests report
explicit skips. Use a dedicated test database and queue, separate from the live service;
the installed service uses `delivery_live` and `agentic-delivery-live`.
The historical baseline was 163 tests with all three configured. On 2026-09-28,
392 tests passed with zero skips against actual Compose PostgreSQL/Temporal and Docker in 107.40 seconds;
Ruff check/format and mypy passed. A later focused run passed 17 dispatch/Temporal CI/Linear tests, including 12 new tests;
the collection of 404 at that checkpoint was not represented as a new full-suite run.
See [implementation status](implementation-status.md) for dated scoped results and the exact collector
image; do not combine overlapping test counts or infer a hosted result at a newer revision.
Hosted CI passed on Python 3.12/3.13 and disposable PostgreSQL/Temporal/Docker services without
provider credentials, plus secret scanning. Check the PR's current revision before merging.

Later scoped operational runs on 2026-09-28 passed 38 active-authorization/pipeline/saved-replay
tests together, three actual PostgreSQL/Temporal/Docker cancellation/expiry/cleanup-error drills,
one PostgreSQL-backed socket HTTP rotation rehearsal, and 31 retention tests with two explicit
Windows skips (symlink privilege and POSIX FIFO). The retention scope includes a disposable
PostgreSQL read-only planning drill. These scopes overlap and cannot be summed into a full-suite
result. Later complete hosted and Windows results are recorded at their exact source
revisions in [implementation status](implementation-status.md); these older scoped runs
do not supersede them. Follow the linked drill documents for synthetic
inputs, exact fault injection and the boundaries of each observation.
The two `scripts/live_*_check.py` scripts are operator-invoked development checks that spend model
tokens; they require explicit environment-file and image inputs and were exercised against the
recorded local services. They are not an unattended benchmark campaign.

For evaluation tooling, `uv run delivery-eval --help` lists implemented qualification,
campaign, scoring and reporting commands. Follow [evals/README.md](../evals/README.md)
and the [qualification controller](qualification-controller.md). Schema validation
alone cannot qualify a task. Executed qualification requires current data/spending
authority, deterministic baseline/oracle checks and two independent metered agent
reviews with immutable provenance. Disputes follow separate adjudication; rights/risk
failures cannot be voted into success. Protected source, oracle/reference material
and private generated artifacts stay outside implementation-agent context.

The [original 36-entry catalog](evaluation-curation.md) remains unqualified. Five
separately acquired historical development tasks have completed qualification; none
has been scored or used in a campaign. The [attempt record](historical-development-attempts.md)
preserves failures and accounting alongside those completions. Owned scorer/adjudicator
calibration is not historical accuracy or validation promotion. Further paid evaluation
needs sufficient current finite authority, including retained unknown liabilities;
restoring provider billing does not enlarge that authority. Do not reset reservations
or claim unobserved human benefit. Automatic low-risk plan approval, human manual
criteria, pilot signoff and human-only merge retain their separately documented rules.

The [local backup drill](local-backup.md) was exercised against the Compose database and artifacts.
Stop all writers before invoking it; the script only restores into a newly created disposable
database. It does not restore Temporal or provider state. For an additional installation,
follow [provider onboarding](provider-onboarding.md) and keep publication disabled until
its inputs and target are verified; the existing installation has passed its bounded
live handoff.

For a closed workflow's damaged read projection, preview first:

```sh
uv run delivery-service recover-projection --config config.local.json --workflow-id WORKFLOW_ID
```

After inspecting the identity and report, use the same command with `--apply`; that invocation
refetches history and checks for concurrent changes. See [projection recovery](projection-recovery.md)
for preconditions, refusal cases and the actual 11-test PostgreSQL/Temporal drill. This operation
preserves financial/provider records and cannot resume a candidate or reconstruct a missing database.

## Inspect correlated operation events

The worker and combined runtime emit [allowlisted JSON operation events](operation-events.md)
for activity timing and model reservation/settlement/recovery. Correlate by workflow
UUID and operation ID. Activity completion is not ticket readiness; an UNKNOWN model
event is not zero spend. Check the durable workflow and ledger before retrying.
The stream is best-effort and only its named event schema is allowlisted; protect
the surrounding private service log and use the bounded exporter below for sharing.
Installation of this newer capability is tracked in [implementation status](implementation-status.md).

## Export bounded operational metadata

Follow [operational export](operations-export.md) to select a new file in a private operator-owned
directory outside repositories and artifact stores:

```sh
uv run python -m agentic_delivery.operations.export --config config.local.json --workflow-id WORKFLOW_UUID --output /private/delivery-exports/workflow-report.json
```

The tool reads a consistent database snapshot and refuses overwrite/protected destinations. It
exports allowlisted correlation/state/spend metadata without artifact bytes, ticket/model output
or secrets. Protect the report because repository IDs and timestamps may still be private.
An actual private PostgreSQL export of workflow `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322` produced
SHA-256 `cac7f2b60b5a8def617cbb15939829cf920c82717347005a5472355241758ef6`.
That snapshot does not reconcile live providers or implement retention/deletion, a full telemetry
service, backup or recovery. Preserve UNKNOWN reservations rather than treating unknown cost as zero.

## Plan artifact retention without deletion

The [read-only retention planner](artifact-retention.md) reads consistent database snapshots,
hash-validates a bounded dedicated artifact store and retains database/external roots plus their
transitive references. It also keeps young files and their older dependencies. It refuses active
work, unknown operations, unresolved publications, special/corrupt files or an unrecognized scope.

Establish that all writers are stopped and settled, the store is dedicated to this control plane,
external roots/legal holds are complete, and backups have independent bytes outside the store.
Then choose an explicit retention age and a new private output path in an existing directory
outside every configured repository and artifact store:

```sh
uv run python -m agentic_delivery.operations.retention --config config.local.json --output C:/private/delivery-exports/retention-review.json --retention-days 90 --dedicated-control-plane-store --writers-quiescent --external-roots-complete --backups-independent
```

Supply each external root with `--retained-root SHA256`. These flags assert facts the tool cannot
discover. Do not assert dedicated scope for shared evaluator/imported artifacts, or force-close
unsettled workflows to obtain a plan. Reports contain hashes/counts/reasons without raw payloads
and refuse overwrite/protected destinations. `CANDIDATE_REVIEW_ONLY` is not safe-to-delete proof:
there is no deletion API, writer lock, complete external-hold discovery or backup validation.
Do not convert the plan into an unattended deletion command. The actual drill used a separate
disposable synthetic database/store and left the shared database and actual artifacts untouched.
