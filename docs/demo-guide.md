# Demonstration guide

The controlled prototype has two demonstration paths: credential-free fixture intake and a configured durable candidate pipeline. Follow [development setup](contributing.md) first. The [implementation status](implementation-status.md) records exercised runs and release limitations.

## Offline fixture intake

Run these from the repository root:

```sh
uv run delivery demos/sample_tickets/low-risk.json
uv run delivery demos/sample_tickets/ambiguous.json
uv run delivery demos/sample_tickets/high-risk.json
```

| Fixture | Expected state | What it demonstrates |
| --- | --- | --- |
| `low-risk.json` | `READY` | Explicit fixture criteria and supplied low-risk metadata pass intake |
| `ambiguous.json` | `NEEDS_CLARIFICATION` | Missing specification prevents readiness |
| `high-risk.json` | `POLICY_BLOCKED` | Sensitive/high-risk work is outside admitted scope |

The output includes policy reasons and local transition records. `READY` authorizes nothing: risk metadata is supplied by the fixture, and the demo has no trusted risk classifier, durable storage, model call, sandbox, or provider connection. A valid blocked fixture is a successful demo invocation; inspect the JSON state rather than treating CLI exit code zero as delivery success. Schema/input errors terminate the command with an error.

## Configured control plane and candidate pipeline

Follow the [runbook](runbook.md) to generate private configuration, start PostgreSQL/Temporal, migrate the database, build and pin the sandbox image, and start API/worker/dispatcher processes. The API command is:

```sh
uv run uvicorn agentic_delivery.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/healthz` for `status: ok` and `mode: durable-control-plane`; this is a liveness response, not proof that database, worker, model or Docker are ready. `/docs` documents intake, workflow, command and provider endpoints. Work-item and command operations require operator authentication. Stop the API with Ctrl+C.

`/readyz` checks database/schema access; it does not establish worker/model/sandbox readiness.
Authenticated `/operations` shows repository-scoped state, spend and dispatch summaries.

Authenticated `POST /work-items` uses an `Idempotency-Key`; receipt is distinct from execution. A plan waits for an authenticated reviewer-role approval bound to the current sequence/specification/plan digests, under an absolute decision deadline. The execution configuration is pinned per attempt; changing model/repository/budget/publication settings requires fresh planning and approval. The worker then builds and tests a pinned candidate in Docker and requests an independent model review. Use the runbook's command-disposition and artifact instructions to inspect results.

A real Anthropic/Temporal/Docker run against the synthetic customer fixture produced `LOCAL_REVIEW_READY`, then ended `POLICY_BLOCKED` at disabled publication. This is the expected observed boundary for that configuration, not a completed remote delivery. The candidate result does not mean a PR was created, merged or deployed. Model-backed runs spend tokens; configure an authorized model/rate card and repository data permission deliberately. Live check scripts under `scripts/` are operator-invoked development checks, not benchmark runs.

The latest recorded run is `b3909403-fead-4093-ae60-c7d20cd3f181`: one candidate attempt on the
actual Compose services, with $0.197655 in recorded model spend. This excludes infrastructure
and human effort; the manifest digest and prior runs are in [implementation status](implementation-status.md).
An explicit eligible terminal rerun creates a new attempt/budget while retaining old spend;
it is blocked when publication is existing or uncertain.

The GitHub App publisher and Linear adapters are implemented, but live App/private-key and authorized Linear workspace credentials are absent. Publication is disabled by default. Do not use a personal token as a product fallback. [ADR-006](adr/ADR-006-verified-local-candidate.md) requires local verification/review before publication and keeps the resulting PR draft for human review.

## Evidence and remaining demonstrations

Run `uv run --no-sync python -m pytest` for unit/contract checks. PostgreSQL, Temporal and Docker integration tests require the environment in the runbook; unconfigured integration tests explicitly skip. Preserve which checks actually ran.

The latest configured local run passed 163 tests, including actual Docker memory/PID/disk
exhaustion and hostile PEP 517 hooks. [Hosted CI passed](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293).
These probes demonstrate
specific controls, not arbitrary-code or multi-tenant escape resistance.

`uv run delivery-eval --help` exposes schema, manifest-validation and trial-report commands.
Follow [the evaluation instructions](../evals/README.md); synthetic control reports are labeled,
and no independently qualified 30+ historical-task campaign has been run.

| Milestone | Demonstration | Evidence to retain |
| --- | --- | --- |
| M1 | Local durable intake and restart checks exercised; live Linear delivery remains | Actual workspace delivery/replay/status evidence alongside signed fixtures |
| M2 | Synthetic candidate build, resource limits and hostile dependency hooks exercised | Exact commands and cleanup records; further runtime-escape and deployment qualification |
| M3 | Independent local review exercised; actual App publication remains | Draft PR, base/head reconciliation, current criterion matrix and human handoff |
| M4 | Some failure paths exercised; complete pilot qualification remains | Full product/security gates, granular recovery, retention and restore drills |
| M5 | Harness implemented; historical campaign remains | Qualified 30+ tasks, frozen paired protocol, human scoring, costs and uncertainty |

Use an operator-owned disposable target repository and synthetic tickets before a live pilot. Record exact versions, inputs, base/head commits, policy, and outcomes. Redact secrets before sharing artifacts. Publish no benchmark numbers until [the evaluation protocol](evaluation-methodology.md) has been executed reproducibly.
