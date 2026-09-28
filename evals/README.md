# Evaluation workspace

The evaluation harness now implements historical-task and trial contracts, manifest validation, protected worker-input projection, isolated candidate scoring, and strict-denominator reporting. **No independently qualified historical dataset, completed model benchmark, or published performance result exists yet.** Offline examples in `demos/sample_tickets/` and CLI test data are explicitly synthetic, not historical benchmark tasks.

The normative plan is [evaluation methodology](../docs/evaluation-methodology.md). It specifies a strict JSONL manifest contract, target 36/minimum 30 historical tasks, grouped development/validation/sealed-test splits, protected scoring, paired arms, finite budgets, and promotion gates. [ADR-004](../docs/adr/ADR-004-context-and-evaluation.md) defines conservative context scope.

## Offline CLI

After `uv sync --locked --extra dev`, export schemas derived directly from the installed contracts:

```sh
uv run python -m agentic_delivery.evaluation.cli schema --kind historical-task --output .local/eval/historical-task.schema.json
uv run python -m agentic_delivery.evaluation.cli schema --kind trial --output .local/eval/trial.schema.json
```

Keep real manifests and results in an evaluator-controlled workspace, outside agent context. A manifest is UTF-8 JSONL with one `HistoricalTask` object per nonblank line. The following examples assume you have placed authorized inputs at the named paths; the repository does not supply historical tasks or curator identities:

```sh
uv run python -m agentic_delivery.evaluation.cli validate-manifest --manifest /path/to/protected/tasks.jsonl --output /path/to/protected/manifest-validation.json
uv run python -m agentic_delivery.evaluation.cli report --manifest /path/to/protected/tasks.jsonl --trials /path/to/protected/trials.json --arm A --split test --output /path/to/protected/report-A-test.json
```

On Windows, use quoted absolute paths such as `"D:\Evaluation Private\tasks.jsonl"`. Validation rejects empty manifests, unknown contract fields, duplicate task IDs and related families crossing splits. `qualification_verified: false` is deliberate: structural validation does not authenticate curator identities, inspect licensing, fetch repositories, verify referenced artifact bytes, or establish baseline/oracle qualification. The JSON schema describes one record; dataset-wide rules are enforced by manifest validation.

Trial input is a JSON **array** of `Trial` objects, not JSONL. Export its record schema to see required status, readiness, regression, cost and timing fields. Reporting rejects unknown tasks, wrong splits and duplicate primary records per task/arm/split across the supplied input. Select arm `A`, `B` or `C` and split `development`, `validation` or `test`. All manifest tasks in that split remain assigned: missing trials appear in `missing_task_ids` and remain in the strict success denominator. Missing measurements cannot be silently removed from the assigned population; cost totals cover recorded trials only.

The output contains the existing harness `report` contract plus SHA-256 hashes of the exact manifest/trial files and a format version. Identical inputs and arguments with the same installed code produce deterministic JSON without timestamps. Retain the repository commit, lockfile, raw inputs and frozen campaign configuration alongside it for reproduction. Report generation does not verify that claimed trial outcomes happened, run models, execute candidates, or satisfy release promotion gates. An output path cannot replace an input file; output replacement is atomic. Exit code 0 means the command completed; invalid input exits 2.

For synthetic control data, add `--synthetic` to `report`; its output is labeled `synthetic-control-report`. Such arithmetic checks are not benchmark measurements. Synthetic test fixtures live only in `tests/test_evaluation_cli.py` and make no claim about real repositories, licenses, curators or artifacts.

## Remaining evaluation work

1. Curate authorized tasks in an evaluator-only workspace outside all agent-visible repositories. Qualify baseline and accepted solutions three times, freeze splits and hashes, and record rejected tasks. Contract-valid records alone do not establish genuine independent qualification.
2. Exercise the implemented isolated scorer and protected worker-input boundary with qualified artifacts. Complete authenticated result collection and the campaign runner around those primitives.
3. Expand hidden-test leakage, tampering, missing test collection, stale cache/head reuse, timeout, infrastructure classification and operational recovery tests.
4. Preregister arms, model/configuration digests, seeds, caps, scoring, and denominator rules. Run development/validation before opening sealed test.
5. Publish a reproducible redacted report and provenance. Keep raw trajectories, accepted patches, withheld tests, private source, and generated run artifacts outside agent context and outside Git.

Protected answers and generated results belong in access-controlled artifact storage. The CLI above validates and summarizes supplied records; it is not an unattended benchmark executor. The documented cost ceiling is a planning parameter, not approval for paid execution.
