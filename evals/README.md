# Evaluation workspace

The evaluation harness now implements historical-task and trial contracts, manifest validation, protected worker-input projection, isolated candidate scoring, and strict-denominator reporting. **No independently qualified historical dataset, completed model benchmark, or published performance result exists yet.** Offline examples in `demos/sample_tickets/` and CLI test data are explicitly synthetic, not historical benchmark tasks.

The normative plan is [evaluation methodology](../docs/evaluation-methodology.md). It specifies a strict JSONL manifest contract, target 36/minimum 30 historical tasks, grouped development/validation/sealed-test splits, protected scoring, paired arms, finite budgets, and promotion gates. [ADR-004](../docs/adr/ADR-004-context-and-evaluation.md) defines conservative context scope.

## Offline CLI

After `uv sync --locked --extra dev`, export schemas derived directly from the installed contracts:

```sh
uv run python -m agentic_delivery.evaluation.cli schema --kind historical-task --output .local/eval/historical-task.schema.json
uv run python -m agentic_delivery.evaluation.cli schema --kind trial --output .local/eval/trial.schema.json
```

Keep real manifests and results in an evaluator-controlled workspace, outside campaign builder/reviewer context. A manifest is UTF-8 JSONL with one `HistoricalTask` object per nonblank line. The following examples assume you have placed authorized inputs at the named paths; the repository supplies only 36 UNQUALIFIED candidate metadata records, not admitted historical tasks or completed reviewer executions:

```sh
uv run python -m agentic_delivery.evaluation.cli validate-manifest --manifest /path/to/protected/tasks.jsonl --output /path/to/protected/manifest-validation.json
uv run python -m agentic_delivery.evaluation.cli report --manifest /path/to/protected/tasks.jsonl --trials /path/to/protected/trials.json --arm A --split test --output /path/to/protected/report-A-test.json
```

On Windows, use quoted absolute paths such as `"D:\Evaluation Private\tasks.jsonl"`. Validation rejects empty manifests, unknown contract fields, duplicate task IDs and related families crossing splits. `qualification_verified: false` is deliberate: structural validation does not authenticate agent reviewer execution, inspect licensing, fetch repositories, verify referenced artifact bytes, or establish baseline/oracle qualification. The JSON schema describes one record; dataset-wide rules are enforced by manifest validation.

Trial input is a JSON **array** of `Trial` objects, not JSONL. Export its record schema to see required status, readiness, regression, cost and timing fields. Reporting rejects unknown tasks, wrong splits and duplicate primary records per task/arm/split across the supplied input. Select arm `A`, `B` or `C` and split `development`, `validation` or `test`. All manifest tasks in that split remain assigned: missing trials appear in `missing_task_ids` and remain in the strict success denominator. Missing measurements cannot be silently removed from the assigned population; cost totals cover recorded trials only.

The output contains the existing harness `report` contract plus SHA-256 hashes of the exact manifest/trial files and a format version. Identical inputs and arguments with the same installed code produce deterministic JSON without timestamps. Retain the repository commit, lockfile, raw inputs and frozen campaign configuration alongside it for reproduction. Report generation does not verify that claimed trial outcomes happened, run models, execute candidates, or satisfy release promotion gates. An output path cannot replace an input file; output replacement is atomic. Exit code 0 means the command completed; invalid input exits 2.

For synthetic control data, add `--synthetic` to `report`; its output is labeled `synthetic-control-report`. Such arithmetic checks are not benchmark measurements. Synthetic test fixtures live only in `tests/test_evaluation_cli.py` and make no claim about real repositories, licenses, executed qualifications or artifacts.

## Remaining evaluation work

Candidate scoring preserves the admitted source's original tests and execution controls,
rejects empty or out-of-policy changes, and revalidates receipt bindings and exact frozen
acceptance/regression collections. A passing minimum count cannot replace a missing frozen
test. Scoring input and result stores must be disjoint; both are evaluator-only because
receipts can contain withheld test names and output. Paired descriptive statistics are available
through [`delivery-eval compare`](../docs/evaluation-comparison.md); this does not execute arms
or authenticate reported results.

1. Use two isolated agent passes to qualify authorized tasks in an evaluator-only workspace outside all campaign builder/reviewer-visible repositories. Qualify baseline and accepted solutions three times, freeze splits and hashes, and record rejected tasks. Keep immutable input/model/configuration/output provenance and use a distinct adjudicator for disagreements; unresolved rights/risk/evidence fails closed. Contract-valid records alone do not establish executed independent qualification.
2. Exercise the implemented isolated scorer and protected worker-input boundary with qualified artifacts. Complete authenticated result collection and the campaign runner around those primitives.
3. Expand hidden-test leakage, tampering, missing test collection, stale cache/head reuse, timeout, infrastructure classification and operational recovery tests.
4. Preregister arms, model/configuration digests, seeds, caps, scoring, and denominator rules. Run development/validation before opening sealed test.
5. Publish a reproducible redacted report and provenance. Keep raw trajectories, accepted patches, withheld tests, private source, and generated run artifacts outside campaign builder/reviewer context and outside Git.

Protected answers and generated results belong in access-controlled artifact storage. The CLI above validates and summarizes supplied records; it is not an unattended benchmark executor. The documented cost ceiling is a planning parameter, not approval for paid execution.

## Agent-led qualification status

[ADR-007](../docs/adr/ADR-007-automated-benchmark-qualification.md) supersedes the earlier requirement
for human benchmark curator names and human rubric scoring at the user's explicit request for
hands-off execution. Two actual independent agent passes, deterministic baseline/reference checks
three times each, and calibrated automated scoring replace that dependency. Human plan approval,
pilot signoff and human-only merges are separate unchanged controls. Human effort and benefit stay
unmeasured unless real observations exist; no generated human identities or minutes are acceptable.

`evaluation/qualification.py` now provides a bounded offline validator for provenance-bound review
and execution artifacts; local and hosted contract/service checks have passed. It validates supplied evidence,
does not invoke qualification agents or create missing receipts, and has not admitted any real task.
The integrated qualifier admission controller remains missing. [Validation-only preparation](../docs/qualification-preparation.md)
now checks trusted configuration/evidence bindings and exact accepted-reference patch application
before execution; `prepare-qualification` returns explicit non-admission metadata. The
[separate evaluation ledger](../docs/evaluation-execution-store.md) and
[bound model-operation receipts](../docs/model-operation-receipts.md) supply accounting/provenance
prerequisites without manufacturing product workflows or granting spending authority.
The CLI verifies every `HistoricalTask` before writing
its metadata-only summary:

```sh
uv run python -m agentic_delivery.evaluation.cli validate-qualification --manifest /path/to/protected/tasks.jsonl --artifacts /path/to/protected/artifacts --output /path/to/private/qualification-validation.json
```

The output cannot be inside the protected artifact store or overwrite input. `worker_input` and
`score_candidate` now refuse unverified structural manifests before reading snapshots or starting
Docker. This is an admission guard, not proof that an arbitrary artifact writer ran agents honestly.
`human_minutes` is nullable; reports preserve missing observations and always leave
`human_time_savings` null.
All 36 candidates remain UNQUALIFIED. See [curation](../docs/evaluation-curation.md) for the exact
record contract and trusted-controller boundary. Full dual-agent scoring/campaign automation,
rights clearance, task eligibility and frozen benchmark execution remain required. The public
candidate catalog is diagnostic preparation, not assumed-valid capability or productivity evidence.

The existing v1 inspection protocol gives qualification reviewers the same `WorkItem` plus six controller-created
status/evidence summaries, with protected reference/oracle content omitted. Summary text still needs
trusted sanitization; schema validation cannot prove absence of semantic answer leakage. Allocate
the two context IDs before hashing the task: `HistoricalTask.reviewers` binds them in qualifier-a/
qualifier-b order. Reference-patch provenance and the separate full reference snapshot are bound
independently. These records describe actual agent contexts, not human reviewer names.

[ADR-010](../docs/adr/ADR-010-executable-qualification-stages.md) adds standalone executable
qualification stages: [metered twelve-run Docker checks](../docs/qualification-runtime.md),
[protected v2 semantic review](../docs/qualification-v2.md) and
[executed development calibration](../docs/evaluation-calibration.md). V2 evaluators inspect actual
authorized source/oracle evidence; initial reviewers never see peers or reference solutions, while
the adjudicator sees both sealed findings. Calibration expectations remain outside model input.
These stages all report `admitted=false`; they do not silently upgrade v1 records or complete the
integrated admission/campaign path. No historical task is qualified by synthetic tests.
