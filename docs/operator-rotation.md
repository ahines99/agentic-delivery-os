# Operator token rotation rehearsal

`tests/test_operator_rotation.py` rehearses API bearer-token rotation over real loopback
HTTP. It uses a temporary private configuration, synthetic random tokens, isolated UUID
repository/workflow identities, and two orderly Uvicorn server instances. It does not
change the operator's actual configuration or credentials, run a worker, contact a
provider, or execute model calls.

## Recorded result

The PostgreSQL-backed local run on 2026-09-28 passed (`1 passed in 1.79s`), preserving
workflow `c12d3f39-5fa4-4a49-8654-c23064d541e7`:

- The old token initially authenticated, and the unconfigured new token was denied.
- Atomic replacement of the temporary config alone left the already-running API using
  its original settings. This explicitly confirms the API's restart requirement.
- After orderly shutdown and startup with the replacement config, the old token received
  HTTP 403 and the new token authenticated over the socket transport.
- The scoped workflow response and list remained identical. A separate synthetic
  repository stayed inaccessible and its stored workflow remained unchanged.
- `admissions_enabled=false` blocked a new submission with HTTP 403, while the new token
  could queue a canonical authorized cancellation with HTTP 202. The old token could not.

The cancellation remains `RECEIVED`: this fixture has no dispatcher or worker and does
not claim the workflow was cancelled. The [active cancellation drill](active-cancellation.md)
separately tests application of the canonical command through Temporal and Docker.

## What the rehearsal does

The test binds an ephemeral socket to `127.0.0.1`, starts an actual `uvicorn.Server`
using the production `create_app` factory and `DELIVERY_CONFIG` lookup, waits for database
readiness, and sends requests through the standard HTTPX network transport. It does not
use `ASGITransport`. Server access logs are disabled, tokens never enter URLs, and the
receipt prints only nonsensitive status observations and the synthetic workflow ID.

Configuration replacement writes a new file in the same private directory, flushes and
fsyncs it, then calls `os.replace`. Only SHA-256 token digests are stored in configuration.
The helper requests mode 0600 on platforms supporting POSIX modes; Windows access is
governed by the directory ACL. Test teardown removes the temporary config even after a
failure. PostgreSQL test rows use unique identities and are retained; no unrelated rows
are deleted. Without `TEST_DATABASE_URL`, the test uses an isolated SQLite file and its
receipt labels that reduced persistence boundary explicitly.

Run the scoped fixture from the project environment with an authorized test database:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://delivery:' + (Get-Content -LiteralPath '.local/postgres-password' -Raw).Trim() + '@127.0.0.1:25432/delivery'
.venv/Scripts/python.exe -m pytest tests/test_operator_rotation.py -q -s
```

No public listener, GUI window, live user token or production configuration is needed.
The test uses a fresh ephemeral port after restart; it does not test listener takeover,
reverse-proxy routing or uninterrupted service at a stable address.

## Operational implications and limits

The API captures settings at startup. To rotate an actual operator token, prepare the new
credential through the authorized secret channel, replace its configured digest in the
private file, validate that file, and restart every API instance consuming it. Verify old-
credential rejection and new-credential access through the real ingress before declaring
the rotation complete. Retain repository/role scope unless an authorization change is
intended. Never put raw credentials in issue comments, evidence exports or shell history.

This rehearsal establishes orderly local restart behavior, not hot reload, zero downtime,
simultaneous revocation across replicas, external TLS protection or automatic deployment
of private configuration. Separate workers/dispatchers and GitHub App/Linear/provider
credentials have distinct loading and rotation paths; this result makes no claim about
their immediate refresh. Admission stopping blocks new work, while authorized read and
cancellation endpoints remain available. It does not automatically stop active work.
