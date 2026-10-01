# 2026-10-01: Product Ops documentation lane behind pull intake

Branch `feat/documentation-lane`, based on `feat/do-3-pull` (`b030d71`, draft PR #16). The lane
code and tests are in `c12b8bf`; the routing test is in `9d719a8`.

## What changed

- **Ported from closed PR #14** (`feat/product-ops-handoff-v2`, which carries PR #9 adapted to the
  current lifecycle graph in `2a3d4db`):
  - `execution/documentation.py`: the Git-object executor (isolated index, empty hooks, atomic ref
    transaction, exact one-file addition).
  - `domain/documentation_review.py`: the OPEN/UNMERGED, human-only local change request.
  - `integrations/product_ops_documentation.py`: the lane controller. It walks INGESTED, ANALYZING,
    READY, PLANNING, IMPLEMENTING, VALIDATING, PR_OPEN, REVIEWING, ACCEPTANCE_CHECK and
    HUMAN_REVIEW with fixed sequences, and resumes by exact replay.
  - `orchestration/dispatcher.py`: a `documentation_addition` start command runs the lane instead
    of starting the Temporal workflow. `service_cli.py` passes a live settings provider so each
    dispatch rechecks current configuration.
  - Tests `test_documentation_execution.py` and `test_product_ops_documentation.py`, the two
    `synthetic-documentation-*.json` fixtures, `scripts/product_ops_wheel_smoke.py` and its CI step.
  - [ADR-034](../adr/ADR-034-product-ops-documentation-handoff.md) and
    [the integration guide](../product-ops-integration.md), rewritten for pull intake.
  - [The 2026-09-30 record](2026-09-30-product-ops-handoff.md), with a dated note that its PER-8
    run used the push endpoint.
- **Not ported.** PR #9's `POST /handoffs/product-ops` endpoint. Pull intake
  ([ADR-038](../adr/ADR-038-product-ops-pull-intake.md)) is the admission path. No lane code or
  test depended on the endpoint: the ported tests call `admit` directly with an operator, and the
  new routing test admits through `linear_monitor.pull_handoff`, which calls `admit(actor=None)`.
- **Kept from DO-3 unchanged.** `config.py`, `integrations/product_ops.py`,
  `operations/linear_monitor.py`, `storage/store.py` and `operations/linear_progress.py`. PR #14's
  versions of those files are older than DO-3's and were not applied.
- **ADR-038** gets two small updates: the push path is no longer described as existing, and the
  "documentation work reaches the standard workflow" consequence notes that this branch restores
  the lane.
- **README** is not edited (a hot file). PR #14's README paragraph is left for a later PR.

## How dispatch routes pull-admitted work

`admit` derives `work_type` from the signed policy version: `doc-add-v1-*` becomes
`documentation_addition`, anything else `software_engineering`. `dispatch_once` reads the run's
work type for each start command. Documentation work goes to `execute_documentation`, which
refuses anything that is not a Product Ops `documentation_addition`. It rechecks the signed
envelope from the inbox, the current approver, approval expiry, cancellation, configuration
digest and the generated ticket, then creates the review branch and projects HUMAN_REVIEW. The
command is marked APPLIED. Every other start command still starts `DeliveryWorkflow`.

## Verification

Windows 11, Python 3.12.10, from the worktree virtual environment after
`uv sync --locked --extra dev`, at `9d719a8` plus these documentation changes:

- `ruff check .`: all checks passed. `ruff format --check .`: 473 files already formatted.
- `mypy`: no issues in 139 source files.
- `pytest -n 16 --dist worksteal -q -p no:cacheprovider -rf`: 3,524 passed, 170 skipped, 0 failed.
- `uv build` then `uv run --no-sync python scripts/product_ops_wheel_smoke.py`: passed. The clean
  wheel imports the signed handoff, packaged schema, executor and Markdown guard.
- `tests/test_product_ops_documentation_pull.py` (new, 2 tests):
  - A synthetic signed documentation handoff is fetched (stubbed) and admitted by `pull_handoff`
    with `admitted_by: product-ops-monitor` and no operator. DO-4 posts "work in progress" on the
    generated ticket. `dispatch_once`, given a Temporal client that fails if used, drives the lane
    to HUMAN_REVIEW with a review branch while `main` is unchanged. DO-4 then posts "in review".
    A second dispatch and report do nothing.
  - A pull-admitted Product Ops software handoff starts `DeliveryWorkflow.run` with the run's ID,
    and the lane is never called.
  - Both fail when the dispatcher is reverted to the DO-3 version.
- The 17 ported lane tests and the DO-3 suites they touch (`test_product_ops.py`,
  `test_product_ops_pull.py`, `test_linear_progress.py`, `test_dispatch_scope.py`) pass: 70 in
  the focused run.

## Findings

- A lane run that has finished sits in HUMAN_REVIEW with no publication record. ADR-033 therefore
  treats the repository as idle while the local review branch is still unmerged. This was already
  true in PR #9 and #14; it is recorded in ADR-034's limits, not changed here.
- A lane failure (for example an expired approval) is recorded as an outbox error and retried
  like any other start command, up to the outbox attempt limit. The run stays in its last legal
  state. This is unchanged from PR #14.

## Not verified

Hosted CI has not run for this branch. The lane has not run behind pull intake against live
Product Ops or Linear, and the change is not installed in the local service.
