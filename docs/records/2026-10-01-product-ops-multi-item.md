# 2026-10-01: Multi-item Product Ops handoffs (DO-5)

Branch `feat/do-5-multi-item`, from `main` at `1b1e0e5` (after PR #17). Decision:
[ADR-039](../adr/ADR-039-product-ops-multi-item-handoffs.md).

## What changed

- `integrations/product_ops.py`:
  - `admit` no longer refuses multi-item specifications or dependencies.
  - It reads back every generated ticket before writing anything.
  - It builds one work item per signed item and passes the set to the store.
- `storage/store.py`:
  - `submit_handoff` writes every item in one transaction, or none. Each item gets a run, a
    held start command and an inbox receipt keyed `{digest}:{work item}`, whose payload records
    the prerequisite run IDs.
  - `handoff_runs`, `waiting_starts` and `release_start` read and release held starts.
  - `delivery_in_progress` ignores a run whose start is still held.
  - `inbox_workflow` is replaced by `handoff_runs`.
- `operations/linear_monitor.py`:
  - `release_ready` queues held starts whose prerequisites merged, while the repository is
    free and still has `automatic_execution`.
  - `prerequisite_merged` accepts a merged publication, or a documentation review head that is
    in the base branch. `head_merged` is now shared with the ADR-034 busy check.
  - `pull_handoff` takes the ticket ID and allows the claim only once that ticket's item is
    released.
  - The monitor loop runs `release_ready` every cycle.
- `operations/linear_progress.py` skips held runs.
- `integrations/product_ops_documentation.py` reads the specification digest from the
  per-item receipt. Older receipts, keyed by the digest itself, still work.
- **Existing tests updated for the new contract.** The admission test now expects the start to
  be held. The pull tests seed a real handoff record and pass the ticket ID.
- **Docs.** ADR-039 is new. ADR-034, ADR-038, the integration guide and the pull contract each
  get a short status update.

## Verification

Windows 11, Python 3.12.10, worktree virtual environment after `uv sync --locked --extra dev`:

- `ruff check .`, `ruff format --check .` and `mypy` (139 source files) pass.
- `pytest -n 16 --dist worksteal -q -p no:cacheprovider -rf`: 3,546 passed, 170 skipped, 0
  failed.
- `tests/test_product_ops_multi_item.py` (new, 10 tests). It uses a real signed W1 → W2
  envelope, built from the synthetic fixture with a `blocks` relation, through the real verifier
  and `admit`. The tests cover:
  - stable runs on re-admission, with held runs not counted as busy;
  - one changed ticket leaving no runs and no receipts;
  - W2 released only after W1 is in `HUMAN_REVIEW` with a merged PR, and exactly once;
  - a failed prerequisite never releasing its dependent;
  - independent items in one repository starting one at a time;
  - switching off `automatic_execution` holding everything;
  - the monitor claiming W2's ticket only after release, with one fetch;
  - a ticket that quotes the digest but is not part of the handoff never being claimed;
  - no progress report for a held run;
  - a documentation prerequisite counting only once its review head is merged, in a real git
    repository.
- Mutation checks, each reverted afterwards. Each of these failed at least one new test:
  - dropping the dependency gate;
  - claiming held tickets;
  - reporting held runs;
  - counting held runs as busy (6 failures);
  - releasing without the busy check;
  - treating an unmerged publication as merged.

## Not verified

DO-5 has not run against live Product Ops or Linear, and it is not installed in the local
service. Dependents of a failed prerequisite stay held, and a cancel command sent to a held run
is not handled. Both are DO-6.
