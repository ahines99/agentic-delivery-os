# Offline campaign preregistration

`agentic_delivery.evaluation.campaign` implements a bounded preparation step for the
[evaluation methodology](evaluation-methodology.md). It does not execute candidates,
call providers, authorize spending, open the sealed test set for scored execution, or
claim that any real task has qualified. No populated campaign is shipped.

## Contract and use

The controller supplies qualified `HistoricalTask` objects, a strict
`CampaignSpecification`, a protected `ArtifactStore`, and a separate output store:

```python
frozen, artifact_digest = freeze_campaign(
    tasks, specification, protected_artifacts, output_artifacts
)
```

The CLI exports schemas with `delivery-eval schema --kind campaign`, `--kind arm-configuration`
or `--kind calibration`, each with `--output FILE`. Once protected inputs and both separate
artifact directories exist, the same preregistration is available as:

```sh
uv run delivery-eval freeze-campaign --manifest /private/tasks.jsonl --specification /private/campaign.json --artifacts /private/qualification-artifacts --output-artifacts /private/frozen-artifacts --output /private/freeze-summary.json
```

The summary must be outside both artifact directories and cannot replace either input. It records
source-file hashes and the frozen artifact digest, with spending unauthorized and calibration
unverified. No ready-to-run historical manifest or campaign is bundled with this repository.

Every prerequisite is checked before the output store receives one content-addressed
`FrozenCampaign`. Failure raises `CampaignFailure`; no partial campaign is written.
The artifact says `PREREGISTERED_NOT_EXECUTED` and `spend_authorized: false`.
It also says `calibration_verified: false`: the metadata/reference validation below
does not certify fixture outcomes and cannot satisfy an execution calibration gate.
Its task entries contain IDs, split/family/repository metadata and manifest/qualification
digests. It contains no source snapshots, oracle paths or test IDs, reference solutions,
model responses, or private review findings. Treat opaque references as metadata;
never grant workers access to the protected store behind them.

Required input fields include the campaign/dataset version, protocol
`agentic-historical-v1`, scoring code commit, rubric/calibration/selection-ledger
artifact references, timezone-aware preregistration timestamp, fixed integer seed,
explicit campaign cap and preparation reservation. `execution_started` must be false.
No human curator identity or human admission vote is required.

## Admission and arm controls

- Between 30 and 1,000 distinct historical tasks, with three equal splits of at least
  ten. The same issue/repository cannot count as multiple tasks at different bases.
- At least three repositories and at least one repository appearing only in the
  sealed test split. Related families cannot span splits.
- Every task passes the existing agent qualification validator against its current
  fully normalized manifest. That validator binds two actual agent receipt contexts
  and executed oracle evidence; a reviewer label or a `passed` flag is insufficient.
- This v1 module accepts the executable-behavior qualification profile only. Thus
  all admitted tasks exceed the methodology's minimum of 24 executable tasks. A
  documentation-only rubric stratum is unsupported and must not be approximated by
  trivial executable tests.
- Arm references are exactly A/B or A/B/C. Each references a concrete, strict
  `ArmConfiguration` artifact. All arms use the same complete model configuration,
  total attempt limits, policy digest, tool-permission digest and builder prompt.
  B adds an independent review prompt; C retains B's review prompt and adds an
  explicit context artifact digest. A has no independent review or C context.
- Model pricing/rate-card fields are positive and concrete. Attempts cannot exceed
  30 active minutes, 10 minutes per command, 100,000 input tokens, 20,000 output
  tokens, USD 5 model cost, USD 1 infrastructure cost, two repair rounds or two
  transport retries. Task budgets must equal the shared arm ceilings. All review,
  correction, scoring and retry work must fit these totals.

Configuration and context artifacts are hash-checked and required to exist. This
does not establish that a future executor obeys them, that a rate card is current,
or that a C context artifact contains a valid measured coverage index.

## Schedule and cost reservation

`select_stability_tasks(tasks, seed)` deterministically selects two IDs from each
split, using SHA-256 ranking of metadata only. The specification must name exactly
these six IDs before execution. Changing input order does not change the schedule.

The `sha256-task-blocks-v1` schedule completes development primary and stability
attempts first, then validation, then sealed test. Within each phase, hash ranking
orders task blocks and interleaves each advertised arm. Each task receives one
primary attempt per arm. Each stability task receives two additional attempts per
arm, with distinct recorded seeds. Arms share the seed for a given task/repeat.
Stability attempts are explicitly labeled and must never replace primary outcomes.
Seeds are provenance, not a guarantee of deterministic hosted inference.

The positive campaign cap cannot exceed 1,000,000,000 microdollars (USD 1,000).
Before freezing, the module requires:

```text
primary attempts   = task count × arm count
stability attempts = 6 × 2 × arm count
worst-case cost    = (primary + stability) × (model cap + infrastructure cap)
                     + preparation reservation
worst-case cost <= campaign cap
```

The preparation reservation must cover all already incurred and remaining
qualification, calibration, adjudication and other preparation costs. It is not
free capacity merely because scored runs have not started. A 36-task three-arm
campaign at the default USD 6 attempt ceiling reserves USD 864 for 144 attempts;
at most USD 136 remains for preparation under the USD 1,000 cap. A 30-task A/B
campaign has 60 primary and 24 stability attempts, reserving USD 504 before
preparation. Unknown pricing or an insufficient cap requires a revised valid
preregistration before execution, never removal of expensive observed failures.

## Evidence and remaining limits

`CalibrationEvidence` binds the rubric and development-only known-pass, known-fail,
and tampering receipt references, plus mandatory safety/false-ready completion
claims. Every receipt must exist and have a distinct digest, including across outcome
roles. This module verifies the controller-owned contract and reference integrity;
it does **not** rerun those fixtures or semantically certify arbitrary receipt bytes.
The calibration producer and its store remain trusted. Tests use explicitly labeled
synthetic fixtures; passing those tests does not qualify a historical task or rubric.

The timestamp and `execution_started: false` assertion cannot prove a campaign has
never run. This pure module does not maintain a run registry, authenticate artifact
writers, enforce one-time sealed-set access, reserve money in a live ledger, or
reconstruct the scoring-code commit. A future controller must enforce campaign
uniqueness, phase gates, sealed-set retirement, per-call reservations, cancellation,
candidate freezing, independent final scoring, and artifact access boundaries.
No task results, human effort estimates, or efficacy claims follow from freezing.
