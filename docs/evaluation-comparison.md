# Paired trial comparison

`agentic_delivery.evaluation.comparison` implements descriptive arithmetic for the
[accepted evaluation protocol](evaluation-methodology.md). It does not execute tasks,
qualify manifests, authenticate scoring evidence, or establish a benchmark result.
Tests use synthetic fixtures only. No historical campaign or human benefit is implied.

## Python API

```python
from agentic_delivery.evaluation.comparison import ArmAssignment, compare_trials

assignments = tuple(
    ArmAssignment(arm=arm, split="validation", task_ids=("task-1", "task-2")) for arm in ("A", "B")
)
result = compare_trials(assignments, trials, seed=0, bootstrap_samples=2000)
```

`trials` is a tuple of existing `harness.Trial` contracts from one primary attempt per
task/arm. Supply the frozen assignments independently of observed trial rows. Every
arm must have the identical nonempty task set and split. The function rejects duplicate
assignments, duplicate trials, unexpected arms/tasks/splits, and strict `PASS` records
without completed passing regressions. It never silently selects records from a mixed
campaign. Report additional seeds and infrastructure reruns separately. Canonical task/arm
ordering makes results invariant to input ordering.

The result is JSON-serializable, schema version 1, with per-arm summaries and comparisons
`B_minus_A`, `C_minus_A`, and `C_minus_B` for supplied arms. Two distinct arms suffice for
the earlier A/B milestone. The offline CLI exposes the same calculation:

```sh
uv run delivery-eval compare --manifest /private/tasks.jsonl --trials /private/validation-trials.json --arms A B --split validation --seed 0 --bootstrap-samples 2000 --output /private/comparison.json
```

The trial file must contain only the requested arms and split; mixed inputs fail rather than
being silently filtered. Use `--synthetic` for arithmetic fixtures. Output binds the exact
manifest/trial byte digests and explicitly reports `qualification_verified: false`: computing
statistics does not authenticate claimed results or admit a dataset.

## Denominators and uncertainty

- Strict success divides `PASS` count by every assigned task, including missing rows.
  Missing rows appear explicitly; `NOT_RUN` is a recorded unsuccessful outcome.
- False readiness divides declared-ready non-`PASS` records by declared-ready records,
  matching the existing harness contract. This is conservative when final scoring is
  incomplete: `Trial` cannot distinguish confirmed incorrectness from unresolved scoring.
  Do not describe that number as confirmed semantic defects without scoring evidence.
- Regression failures divide failed completed regression runs by completed regression
  runs. Incomplete regressions, including missing records, divide by assigned tasks.
  Undefined conditional rates and their intervals are `null`, never zero.
- Binary per-arm rates carry integer numerators/denominators and 95% Wilson intervals.
  Comparisons use a fixed-seed Python `random.Random` paired task bootstrap: draw the
  assigned task count with replacement, sharing indices across both arms and all metrics;
  recompute ratios per sample; report candidate minus baseline. The 95% percentile interval
  uses linear interpolation at `(sample_count - 1) * percentile`. Undefined ratio samples
  are excluded and both valid/undefined counts are disclosed; sparse conditional intervals
  must be interpreted with those counts. Defaults are seed 0 and 2,000 samples; the caller
  can freeze another integer seed and 100–100,000 samples before observing results.
- Discordant success pairs show candidate-only, baseline-only, both and neither successes
  over the complete assigned set. They do not by themselves establish reviewer defect
  catches or false alarms: those require separate observations absent from `Trial`.

Intervals are descriptive task-level uncertainty, not simultaneous inference across all
comparisons. Repository/family clustering and correlated model behavior are not modeled.
Constant empirical outcomes can produce zero-width bootstrap intervals, including when
neither arm ran any tasks; this is not proof of equality or zero underlying uncertainty.
Preserve assignment/recording counts, missing IDs and per-arm Wilson intervals alongside
paired intervals. Do not use repeated seeds as independent task observations.

## Cost and human observations

Costs include model and infrastructure microdollars for every recorded trial, including
failures. `recorded_microdollars` and its assigned-task average are observed subtotals;
with missing rows they are only lower bounds, not zero-imputed complete spend. Complete
total, mean per assigned task, and cost per success are `null` until every assigned trial
has a cost record. Cost per success is also `null` when there are no successes.

Paired cost differences and intervals use only tasks with a recorded cost in both arms,
explicitly labelled `cost_microdollars_observed_pairs`, and report their denominators.
These complete-pair estimates can be selected by missingness; they are not full-campaign
cost comparisons until coverage is complete. Shared assigned-task bootstrap draws with
no observed cost pairs have undefined ratios and are counted as such. Accounting certainty
is limited by the supplied `Trial` contract, which has no unsettled-reservation field;
resolve unknown spend before creating a purported complete trial record.

Actual `human_minutes` observations retain their count and recorded total, distinguishing
observed zero from no observation. `human_time_savings` is always `null`: this contract
does not provide a human counterfactual, and automated elapsed time is not human time saved.
The comparison module does not invent unrecorded effort or infer functional acceptance,
criterion coverage, repair effort, calibration, or provenance absent from its inputs.
