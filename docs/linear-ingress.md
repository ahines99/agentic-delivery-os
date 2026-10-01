# Linear and GitHub webhook ingress

For the complete delivery path, use `create_delivery_gateway`. It accepts exact
`POST /webhooks/linear` and `POST /webhooks/github` callbacks on the same endpoint,
forwarding each to its matching private API route on port 18090. GitHub callbacks
carry only the SHA-256 signature, delivery ID, event type and JSON content type.
The API validates the signature, installation and repository and persists PR/CI
observations. The gateway keeps the same body/time limits and generic responses
described below. Operator routes remain inaccessible through this gateway.

```sh
python -m uvicorn agentic_delivery.api.app:app --host 127.0.0.1 --port 18090 --no-access-log --no-proxy-headers
python -m uvicorn agentic_delivery.api.linear_ingress:create_delivery_gateway --factory --host 127.0.0.1 --port 18091 --no-access-log --no-proxy-headers --limit-concurrency 16 --h11-max-incomplete-event-size 8192
```

Point the HTTPS reverse proxy at port 18091 and configure the two provider callbacks
with their respective paths. Start the gateway without service credentials. Run the
worker and dispatcher as described in the [runbook](runbook.md). This provides the
local application routes; persistent HTTPS hosting remains an environment prerequisite
for public callbacks. The GitHub App itself is installed and published PRs #6 and #7
through outbound polling (see the [live record](live-automatic-delivery.md)); signed
live callbacks through this gateway remain unconfigured. The older Linear-only entry
point below stays available.

## Linear-only entry point

`agentic_delivery.api.linear_ingress:create_gateway` exposes only an exact
`POST /webhooks/linear`, without a query string. Run it on loopback port 18091
and the existing delivery API on loopback port 18090. Point any separately
authorized public HTTPS tunnel at port 18091 only. The API's operator routes,
PostgreSQL, Temporal, and Docker must remain private.

The gateway checks header shape and bounds, retains raw signed body bytes, and
forwards only Linear signature/delivery/event/timestamp and JSON content-type
headers to the fixed loopback endpoint. It never forwards Authorization,
cookies, proxy headers, upstream response bodies, or redirects. The API remains
responsible for HMAC, freshness, organization, team, assignee and durable intake
validation. A gateway header check is not signature authentication.

Requests have a four-second total deadline including semaphore wait and body
upload, a 256 KiB body limit, 8 KiB/32-header limits and eight active requests.
Run Uvicorn with access logging and proxy-header interpretation disabled and
an explicit HTTP parser/header bound. The gateway has no secret/configuration
loader and should receive no provider, signing, model or operator credentials.
The API receives only its required configuration and signing secret.

```sh
python -m uvicorn agentic_delivery.api.app:app --host 127.0.0.1 --port 18090 --no-access-log --no-proxy-headers
python -m uvicorn agentic_delivery.api.linear_ingress:create_gateway --factory --host 127.0.0.1 --port 18091 --no-access-log --no-proxy-headers --limit-concurrency 16 --h11-max-incomplete-event-size 8192
```

No worker or dispatcher is needed to test signed durable intake. Starting those
processes is a separate action because queued issues can trigger planning and
provider usage. Creating a public tunnel, registering a webhook, or changing a
real issue likewise requires the relevant operator authorization. Local gateway
unit checks and unsigned rejection do not establish actual provider delivery or
duplicate-delivery behavior. A temporary tunnel is a test endpoint, not a durable
production deployment.

Use private, ignored, operator-owned secret files and disable request header/body
logging throughout the ingress path. Keep exact child process identities for
targeted shutdown; do not restart unrelated services or expose the full API.
## Recorded live temporary intake

On 2026-09-29, the pinned cloudflared 2026.9.3 binary was verified against its published
SHA-256 before creating a temporary Quick Tunnel to the gateway. External checks returned
404 for API documentation, operations, work-item and GitHub webhook paths, and 403 for
unsigned and invalid-HMAC Linear requests. This is a test endpoint, not durable hosting.

The authorized workspace admin key created one Issue-only webhook for the configured team,
then controlled owner-assigned ticket PER-5. Its actual signed `create` event committed one
inbox receipt, workflow `b6da414c-43ae-41a6-a0a4-6ffb44c4ee64`, start command and pending
outbox record to PostgreSQL. At intake, model operations and spending were zero.

A later actual Todo-to-Backlog update preserved the ticket's title and provider-canonical
description. It produced a second inbox receipt and no additional workflow or start command.
The original update body's bytes were reconstructed only after matching the stored SHA-256;
an exact signed replay within the timestamp window returned HTTP 200 and left counters at
two inbox receipts, one command and one outbox record. This replay was sent by the test
controller; it does not claim a provider retry or production load test.

Linear normalized the description supplied at issue creation. An initial test preflight
correctly refused before any mutation because it compared that request text to the stored
provider version. The successful test bound to the exact original signed inbox description,
preserving the same current-content check used by the product.

The API and gateway use separately tracked hidden processes bound only to loopback. The
gateway has no credentials. No worker or dispatcher was started for these intake checks;
planning, approval, candidate execution and review-state handoff are separate evidence.
After the planning checks below, the exact temporary webhook was disabled through one
mutation and a separate provider read verified `enabled=false`. The tunnel, API and gateway
were stopped after checking their original process identities; ports 18090, 18091 and 18092
had no remaining listeners. Both planning workers were absent. All ticket, workflow, plan
and accounting records were retained; unrelated local services remained unchanged. A new
durable endpoint and configured webhook are still required for ongoing intake.

## Actual ticket-to-plan checks

After intake testing, each controlled issue received one narrowly scoped Temporal dispatch
and a planning-only worker. PER-5 reached `NEEDS_CLARIFICATION` with five criteria and seven
questions. Its single settled call used 2,091 input and 3,007 output tokens, costing 85,630
microdollars. Its original workflow and queue remain available for an authorized continuation.

PER-6 describes an exact optional status filter within the already onboarded owned sample
repository. It reached `PLAN_REVIEW` with five criteria and no clarification questions. Its
single settled call used 2,466 input and 2,101 output tokens, costing 64,855 microdollars.
The plan binds base `e00796e4cccc5371efe8603fabe883e1aba77eb4` and artifact
`4d8ec3ac32f6092fb3e4fc79a4eafaa114b4a8260849a094582b14e3562abcda`.

Both accounts retained zero reserved balance, and both workers were gracefully stopped and
their absence verified. Plan prose and readable review files remain private. No approval,
candidate build, publication or review-state update was issued. These are real provider and
orchestrator observations for owned test tickets, not historical benchmark results or a
complete Linear-to-GitHub delivery.
