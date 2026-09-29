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
