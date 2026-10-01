# 2026-10-01: Product Ops documentation lane behind pull intake

Branch `feat/documentation-lane`, based on `main` at `4023fe9` (DO-3, PR #16). It brings back the
documentation lane from closed PR #9 behind pull intake, before DO-5.

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
`uv sync --locked --extra dev`, on the branch rebased onto `main` at `4023fe9`:

- `ruff check .`: all checks passed. `ruff format --check .`: 475 files already formatted.
- `mypy`: no issues in 139 source files.
- `pytest -n 16 --dist worksteal -q -p no:cacheprovider -rf`: 3,535 passed, 170 skipped, 1
  failed. The failure was the known timing-sensitive
  `test_phase_revocation_during_third_review_retains_the_fence[v2]`, which passed when rerun
  alone.
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

- **Fixed:** a lane run that had finished sat in HUMAN_REVIEW with no publication record, so
  ADR-033 treated the repository as idle while the local review branch was still unmerged. The
  busy check now covers open review branches (ADR-034 update).
- **Fixed:** a lane failure such as an expired approval was retried up to the outbox attempt
  limit. Authority failures now end the run once; transient failures still retry.
- **Fixed:** Product Ops' path-derived repository IDs (for example
  `repo-a8a12ccb002929f9de78b80e29a3e1bb` for this checkout) were refused as "Repository is not
  onboarded". The `product_ops_repository_ids` setting now maps them.
- `tests/test_documentation_lane_guards.py`: 12 passed. The tests cover:
  - alias admission into the configured repository, and refusal of an unmapped ID;
  - an ID that maps to two repositories, and digest exclusion;
  - `POLICY_BLOCKED` and `CANCELLED` endings with no retry;
  - transient retry;
  - no projection after the handoff;
  - open, merged and deleted review branches in a real git repository, and failing closed.

## Installation for the end-to-end test

These are in addition to the DO-3 settings in `2026-10-01-product-ops-pull.md`.

- **Repository entry:**
  - `"product_ops_repository_ids": ["repo-a8a12ccb002929f9de78b80e29a3e1bb"]`
  - `local_repository` pointing at this checkout.
- **`product_ops` block:**
  - `documentation_capability`: the exact object Product Ops writes at its runbook step 3.
  - `policy_versions`: must include that capability's `doc-add-v1-…` version.
  - `documentation_approvers`: `["alex-hines"]`.
- **Approver as operator.** The lane also requires the approver to be a configured operator with
  the `reviewer` role on the repository. `alex-hines` must therefore exist in `operators`.
- **Base commit.** The capability's `base_sha` is the current `main` of this repository when the
  lane is bound. Nothing may merge into the repository during the run.
- **Live checkout is untouched.** The lane writes only git objects and a review-branch ref, with
  no checkout, so the working tree the installed service runs from is unaffected.

## Not verified

Hosted CI results are on the pull request. The lane has not run behind pull intake against live
Product Ops or Linear, and the change is not installed in the local service.
