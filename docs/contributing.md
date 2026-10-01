# Development guide

Read [the accepted plan](plan.md), [implementation status](implementation-status.md), [repository guidance](../AGENTS.md), and relevant ADRs before changes. Work within the next unmet milestone gate. The repository is a controlled prototype; implemented adapters and synthetic live checks do not establish a completed MVP.

## Environment

Use Python 3.12 as the baseline; CI also checks 3.13. Install Git and [uv using Astral's supported installation instructions](https://docs.astral.sh/uv/getting-started/installation/). CI pins uv 0.12.18. On Windows, `winget install --id=astral-sh.uv -e` is a supported option; open a fresh terminal afterward. On macOS, Homebrew users can run `brew install uv`. The linked instructions cover Linux and standalone installers.

From this repository, on either Windows PowerShell or a Unix shell:

```sh
uv python install 3.12
uv sync --locked --extra dev
uv run --no-sync python -m ruff check .
uv run --no-sync python -m ruff format --check .
uv run --no-sync python -m mypy
uv run --no-sync python -m pytest -n auto --dist worksteal
```

Tests run in parallel with pytest-xdist. On machines with more than 16 logical CPUs, use
`-n 16` instead of `-n auto`: heavier oversubscription starves the deliberate short waits
and deadlines in concurrency tests. Plain `python -m pytest` still runs serially. Keep
`-m integration` runs serial because those tests share one configured database and Temporal server.

`uv` creates the project `.venv`; activation is optional. If a Windows policy prevents activation scripts, invoke `.venv\Scripts\python.exe -m pytest` directly (and the same form for ruff/mypy). On Unix use `.venv/bin/python -m pytest`. Do not weaken the machine's execution policy to activate a virtual environment. First-time synchronization downloads dependencies; offline intake fixtures need no external service credentials or Docker.

For actual control-plane development, follow [the runbook](runbook.md): generate ignored private config, start Compose PostgreSQL/Temporal, migrate, and build a fixed Docker sandbox image. `config.local.json` (or `DELIVERY_CONFIG`) owns runtime settings; `.env.example` documents process environment references and is not auto-loaded. Set authorized model configuration/rates and repository data permission before real calls. Keep publication disabled until GitHub App and Linear onboarding and the relevant gates are completed.

Service tests use `TEST_DATABASE_URL`, `TEST_TEMPORAL_ADDRESS`, and `TEST_SANDBOX_IMAGE`. Run `uv run --no-sync python -m pytest -m integration` against disposable configured services. A normal test run skips integrations whose environment is absent; record those skips and do not describe them as passing integration checks. Live model checks consume paid tokens and require deliberate operator invocation.

## Changes and checks

Keep domain rules independent of provider SDKs and Temporal. Validate external inputs at boundaries, reject unknown fields and unsupported versions, and test state/policy denial paths. Add regression tests for changed behavior; security boundaries need adversarial cases, and durable side effects need retry, duplicate, stale-input, and crash-recovery cases. Do not substitute mocks for release evidence of real integrations.

Format using `uv run --no-sync python -m ruff format .`, then rerun the four checks above. A green unit suite establishes tested behavior only. Real services, actual provider deliveries, sandbox controls and live publication require their own recorded verification.

Dependency changes should update `pyproject.toml` and `uv.lock` together using `uv lock` followed by `uv sync --locked --extra dev`; review the lock diff and run the checks. `--locked` detects an outdated lockfile instead of silently changing it. See [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/). Keep credentials, local `.env` files, execution artifacts, and historical reference answers out of Git and agent context.

## Parallel workstreams

Several agents and people work at once. Conflicts are prevented by process:

- **One trunk.** `main` is the only integration branch. `feat/governed-delivery-platform`
  is frozen after its squash merge into `main` and receives no new PRs.
- **Short branches.** Branch from current `origin/main` in a separate worktree, make one change,
  rebase onto `main` right before opening the PR, and merge PRs one at a time. A PR that
  falls behind `main` is rebased by its owner before merging, never resolved through the web editor.
- **No shared logs.** Verification evidence goes in a new file under [records](records/README.md).
  The status documents are updated only by a dedicated consolidation PR.
- **ADR numbers.** Use the next number after the highest one on `main` and in open PRs.
- **Hot files.** Before editing `README.md`, `AGENTS.md`, `docs/plan.md` or `docs/backlog.md`, check
  `gh pr list` for open PRs that touch the same file.
- **The installed service.** It runs from the root checkout. Change that checkout only through
  the supervised upgrade procedure in [the local upgrade record](local-runtime-upgrade.md).

Automatic deliveries follow the same principle at runtime:
[ADR-033](adr/ADR-033-one-delivery-per-repository.md) admits one delivery per repository at a time.

Use [the task template](../.github/ISSUE_TEMPLATE/task.yml) for bounded backlog work. PRs include criterion-level evidence and limitations, and changes to material architectural decisions update an ADR. Every MVP merge is human; repository protection and product-provider onboarding require independent verification.

## CI and provider onboarding

[CI](../.github/workflows/ci.yml) runs on pull requests, pushes to `main`, and manual dispatch. Quality jobs check Python 3.12 and 3.13 with locked dependencies. A separate integration job provisions disposable PostgreSQL, Temporal and a Docker test image and runs marked service tests. Actions are pinned; checkout does not persist credentials, token permissions are read-only, and jobs have finite timeouts. CI does not publish, deploy or use model/Linear/GitHub App secrets.

Require both quality jobs and service integration checks, human reviews, stale-review dismissal, and protected branches without bot bypass when configuring the hosted repository. Verify those settings independently of YAML. Review action/tool updates and refresh immutable pins from upstream. Product GitHub publication requires a repository-scoped App installation and private key; project-maintenance CLI credentials are not a fallback. Actual Linear delivery needs an authorized workspace/team/worker, signing/API secrets and HTTPS callback. Keep trusted credentials separated from candidate code as specified in the [security model](security-model.md).
