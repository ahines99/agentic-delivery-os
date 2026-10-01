# 2026-09-30: Product Ops handoff and constrained documentation lane

This record replaces PR #9's edits to the status documents and its `docs/per7-validation-record.md`.
It keeps the original PER-7/PER-8 evidence below unchanged, then records the port of that work onto
the current stack (main + PRs #10, #11 and #12) on branch `feat/product-ops-handoff-v2`.

> **Note (2026-10-01).** The PER-8 run below was admitted through PR #9's authenticated push
> endpoint, `POST /handoffs/product-ops`. That endpoint was not carried forward: on
> `feat/documentation-lane` the only admission path is the Linear monitor's pull intake
> ([ADR-038](../adr/ADR-038-product-ops-pull-intake.md)). Statements below about "the
> authenticated Delivery API" and HTTP 202 replays describe that historical run only. See the
> [documentation lane record](2026-10-01-documentation-lane.md).

## Summary

The [signed intake and constrained documentation lane](../product-ops-integration.md) use
Delivery-owned persistence. Actual approved PER-7 work, published as PER-8, was admitted once
and reached HUMAN_REVIEW with commit `b44c681ffa1df5fe0094520219a283416e35239b`, an exact
one-file addition and an OPEN/UNMERGED local change request. No model calls, target-repository
execution, GitHub push or merge occurred in Delivery. No hosted verification of PR #9 was
claimed. General multi-ticket scheduling and cross-system supersession remain open.

## PER-7 approved-work integration evidence (from PR #9)

Observed 2026-09-30 UTC. Product Ops defines and approves work; Delivery stores and executes
the signed work in its own database. This controlled pilot does not establish general
autonomous delivery, independent product quality or MVP completion.

### Live result

The human operator approved Product Ops revision 3 with digest
`2fae2dbaf44396f8875ef2b0789beb8788742886ced8289b5500181c8867f6fe`, its exact constrained
documentation policy and one generated Linear work item. Product Ops published PER-8, held
the initial Markdown read-back mismatch, then reconciled the existing ID read-only.

The actual authenticated Delivery API verified the signed envelope and current Linear ticket,
and admitted workflow `f109d0c5-ee2b-43e3-8cea-159aacbe3dc6`. The existing transactional outbox
dispatcher produced the exact inert Markdown addition and projected HUMAN_REVIEW.

- Commit: `b44c681ffa1df5fe0094520219a283416e35239b`.
- Parent: `d9604888843e2b0ba60cc49565339a910e3ec393`.
- Branch: `delivery/doc-2fae2dbaf44396f8875ef2b0789beb8788742886ced8289b5500181c8867f6fe`.
- Change: only `A docs/pilot-success.md`, 98 UTF-8/LF bytes including the final newline.
- File SHA-256: `26fc9bf3cefc5e743f0e8d71c17d617608b48e48bad692f78811d86b511a1b2d`.
- Immutable change-request SHA-256:
  `842ac4d16207fe1ec5ab4b62504ba4e6debe60a05e2b4e2dbb22c929bceb286c`.
- Review state: OPEN, UNMERGED, human-only merge and `auto_merge=false`.

Actual API replay returned HTTP 202 with the same workflow; producer replay and repeated
completed execution also returned their prior receipts. The database still contained one
run, one inbox and one start outbox. The target main checkout remained clean and unchanged.
Delivery made no model calls, ran no target-repository code, and performed no push or merge.

Product Ops reserved $1.489624 under its $2 allocation; Delivery's $3 allocation was unused.
The combined $5 authorization was preserved. These are reservations, not verified billing.

### Verification boundary

The 40 focused public-contract, Markdown-tamper, admission, authorization, storage and Git
tests passed on Windows Python 3.12.10 and Linux Python 3.12.14. Ruff/format (391 Python files),
mypy (125 source files), locked dependency checks, package builds and clean-wheel imports of
the signed contract, schema, executor and description guard passed on both platforms.

The complete Linux collection passed: **3,013 passed, 91 explicitly skipped**, covering all
3,104 collected cases from 123 files in eight disjoint test processes. Each process exited 0;
the slowest finished in 412 seconds. The tested code was exported from commit `4fbb58f` into
an isolated Linux checkout. Only provenance/documentation updates followed. The much slower
Windows full run was stopped after the complete Linux result; it is not reported as passing.
The 40 focused Windows tests passed separately. Hosted Actions have not run for this branch;
the optional external-service test environment was not configured for these runs.

The exact pinned Gitleaks CI image passed both the exported source inventory and an isolated
Git snapshot. Six initial findings were two deterministic public fixture operation digests,
not credentials. The exception requires both the named synthetic fixture path and exact
`operation_key` line/value; all default detectors remain enabled. An altered operation digest
in that same fixture path was detected in an actual negative scanner probe.

Vendored public files match Product Ops commit `f04d8453244e2249b1e93c8bd6ce580d6a40335d`;
the package's `UPSTREAM.md` records committed-blob SHA-256 hashes and license provenance.
Product Ops persistence, private receipts and credentials are not vendored.

### Reproduce

```powershell
python -m uv sync --locked --extra dev --python 3.12
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
python -m uv build
python -m uv run --no-sync python scripts/product_ops_wheel_smoke.py
```

### Remaining work

Actual admission rejects multi-item DAGs and replacement revisions. The exercised lane accepts
only the exact installed inert-file capability; it is not a general builder. Atomic batch
admission/dependency scheduling comes next, followed by cross-system source supersession and
cancellation propagation, per-prompt budget/enrollment automation, hosted PR acceptance and
independent evaluations. Signed lifetimes and dispatch rechecks limit disconnected authority;
instantaneous producer-side revocation is not claimed. See [integration](../product-ops-integration.md)
and [ADR-034](../adr/ADR-034-product-ops-documentation-handoff.md).

## Port onto the current stack (2026-10-01)

PR #9 (`4fbb58f`, `5aa2e14`, based on `4d71ce3`) was replayed onto `feat/linear-progress`
(`e4b28ed`) and supersedes that PR.

- **Configuration.** `Settings` keeps the stack's Linear routing, pickup and progress settings
  and adds `product_ops: ProductOpsTrust | None`, which enters the execution digest only when set.
- **Lifecycle.** The store now rejects illegal `domain.lifecycle` edges. PR #9 projected
  NEW -> IMPLEMENTING -> HUMAN_REVIEW, which the graph forbids. The lane now walks INGESTED,
  ANALYZING, READY, PLANNING, IMPLEMENTING, VALIDATING, PR_OPEN, REVIEWING, ACCEPTANCE_CHECK and
  HUMAN_REVIEW with fixed sequences and reasons, and resumes from any of those states by exact
  replay. PR_OPEN names the local change request, not a GitHub PR. The check was not relaxed.
  The live PER-8 audit trail above was recorded under the earlier two-step projection; a run
  left mid-flight by that earlier code conflicts on resume rather than being silently rewritten.
- **ADRs.** PR #9's ADR-022 and ADR-023 are renumbered to
  [ADR-034](../adr/ADR-034-product-ops-documentation-handoff.md) and
  [ADR-035](../adr/ADR-035-linear-markdown-readback.md).
- **Status documents.** PR #9's `implementation-status.md` paragraphs are carried here instead.
- **Dependencies.** `jsonschema`, `markdown-it-py==4.2.0` and `types-jsonschema` were added to the
  stack's dependencies (including `pytest-xdist`) and `uv.lock` was regenerated with `uv lock`.
  CI keeps `-n auto --dist worksteal` and adds the clean-wheel Product Ops smoke step.

### Verification on Windows, Python 3.12, from the worktree virtual environment

- `uv sync --locked --extra dev`: passed.
- `ruff check .`: passed. `ruff format --check .`: 467 files already formatted.
- `mypy`: no issues in 138 source files.
- `pytest -n 16 --dist worksteal`: 3,482 passed, 170 skipped, 0 failed.
- `uv build` then `scripts/product_ops_wheel_smoke.py`: passed.
- New tests cover the legal edge sequence, resume after interruption at four points, and
  refusal of shortcut edges and of runs outside the lane's own path.

### Not verified

Hosted CI has not run for this branch. The ported lane has not been exercised against live
Product Ops or Linear; the PER-8 evidence above predates the port.
