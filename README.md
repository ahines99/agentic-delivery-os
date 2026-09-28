# Agentic Delivery OS

A governed agent-assisted delivery platform that aims to convert issue-tracker tickets
into tested, independently reviewed pull requests, with evidence and human control of merges.

**Status: implemented controlled prototype; complete MVP release gates remain open.**
The accepted implementation plan is [docs/plan.md](docs/plan.md). The project retains the
local directory name `agentic-delivery-engineer`; the product/package name is Agentic Delivery OS.

```text
Linear -> Requirements -> Risk policy -> Plan -> Isolated build
       -> Independent verification -> Evidence -> Human-reviewed GitHub PR
```

Implemented and exercised locally: authenticated intake and plan approval, PostgreSQL
inbox/outbox and audit storage, Temporal workflows, real Anthropic planning/build/review,
bounded Docker execution, independent test runs, and digest-verified candidate artifacts.
The local suite passed 163 tests with actual PostgreSQL, Temporal and Docker, including
resource-exhaustion and hostile dependency-hook cases. [Hosted CI passed](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293)
on Python 3.12/3.13, real service integration and secret scanning.
A synthetic customer task reached `LOCAL_REVIEW_READY`; its durable workflow stopped at
`POLICY_BLOCKED` because publication was disabled. No PR, merge, or deployment is implied.

GitHub App publication and Linear adapters exist and have contract/fixture tests, but live
GitHub App credentials and authorized Linear workspace keys are not configured. Complete
recovery/security qualification and the independently scored 30+ historical-task evaluation
remain release gates. The Docker checks establish named controls, not safety against arbitrary
hostile code. See [implementation status](docs/implementation-status.md) for recorded runs,
verification boundaries, and outstanding work. The original proposal remains preserved in
[docs/reference/original-handoff.md](docs/reference/original-handoff.md).

## Local quickstart

Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/) are required.
No credentials or Docker are needed for the offline intake fixtures.

```sh
uv sync --extra dev --locked
uv run delivery demos/sample_tickets/low-risk.json
uv run delivery demos/sample_tickets/ambiguous.json
uv run delivery demos/sample_tickets/high-risk.json
```

The samples produce `READY`, `NEEDS_CLARIFICATION`, and `POLICY_BLOCKED`. `READY` means only
that supplied fixture metadata passed intake checks; no model, code execution, or PR occurs.
For the actual control plane, follow the [local runbook](docs/runbook.md) to configure
PostgreSQL, Temporal, a fixed sandbox image, operator authentication, and an authorized model.
The API includes authenticated work-item, workflow, rerun and command endpoints; `/healthz` is
liveness only, `/readyz` checks the database, and authenticated `/operations` summarizes scoped
state, spending and dispatch. Model-backed runs spend tokens and require explicit data authorization.
Publication remains disabled by default, and there is no personal-token fallback.

```sh
uv run --no-sync python -m ruff check .
uv run --no-sync python -m ruff format --check .
uv run --no-sync python -m mypy
uv run --no-sync python -m pytest
```

`delivery-eval` provides offline schema export, manifest validation and trial reporting; see
[the evaluation workspace](evals/README.md). These commands do not run a benchmark or verify
historical-task qualification. Integration tests explicitly skip without the runbook's service variables.

## Project map

| Path | Purpose |
| --- | --- |
| [docs/plan.md](docs/plan.md) | Accepted scope, sequencing, decisions, completion gates |
| [docs/implementation-status.md](docs/implementation-status.md) | Current capabilities, recorded live checks, and remaining release gates |
| [docs/runbook.md](docs/runbook.md) | Local service setup, authenticated operations, and recovery |
| [docs/product-spec.md](docs/product-spec.md) | Product requirements and MVP acceptance |
| [docs/architecture.md](docs/architecture.md) | Components, contracts, storage, recovery |
| [docs/security-model.md](docs/security-model.md) | Trust boundaries and execution controls |
| [docs/evaluation-methodology.md](docs/evaluation-methodology.md) | Reproducible evaluation protocol |
| [docs/backlog.md](docs/backlog.md) | Dependency-ordered implementation issues |
| [docs/research/](docs/research/) | Five independent research reviews |
| [docs/adr/](docs/adr/) | Architecture decision records |
| `src/agentic_delivery/` | Control plane, provider adapters, candidate pipeline, runner, and evaluation harness |
| `demos/sample_tickets/` | Credential-free intake fixtures |
| `tests/` | Unit, contract, and opt-in PostgreSQL/Temporal/Docker integration tests |

See [contributing](docs/contributing.md) for development and
[demo guide](docs/demo-guide.md) for verified behavior and planned demonstrations.
Synthetic live checks are development evidence, not benchmark results or cost-saving claims.
