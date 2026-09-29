# Narrow Linear ingress

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
The webhook and tunnel are temporary test infrastructure requiring tracked cleanup or
replacement before durable operation.
