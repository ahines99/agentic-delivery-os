# Offline campaign preregistration

`agentic_delivery.evaluation.campaign` implements a bounded preparation step for the
[evaluation methodology](evaluation-methodology.md). It does not execute candidates,
call providers, authorize spending, open the sealed test set for scored execution, or
claim that any real task has qualified. No populated campaign is shipped.

## Contract and use

The controller supplies current `independent-agents-v2` tasks, a strict
`CampaignSpecification`, a protected `ArtifactStore`, a separate output store,
and the concrete in-process `QualificationAuthority`:

```python
frozen, artifact_digest = freeze_campaign(
    tasks,
    specification,
    protected_artifacts,
    output_artifacts,
    authority=authority,
)
```

The authority revalidates each task's complete evidence chain and current `campaign`
use grant. It also revalidates the executed development calibration, including
ledger/model receipts, rather than accepting legacy receipt references or boolean
claims. All tasks must bind the same qualification model configuration, calibration
specification/evidence and rubric. The qualification model is a separate role from
the A/B/C implementation model and need not be the same model.

Every prerequisite is checked before one content-addressed schema-2 `FrozenCampaign`
is written. Failure raises `CampaignFailure`; no partial campaign is written. The
artifact says `PREREGISTERED_NOT_EXECUTED`, `spend_authorized: false`, and
`calibration_verified: true`. That calibration flag records successful validation at
freeze time; the artifact is not a current authorization capability or proof that any
campaign attempt ran. Current grants and calibration expiry must be checked again
by any future campaign executor.

Task entries contain IDs, split/family/repository metadata and manifest/qualification
digests. They omit source snapshots, oracle paths/test IDs, reference solutions,
model responses and private review findings. Never give workers access to the
protected store behind these opaque references.

The offline CLI has no trusted authority loader. `freeze-campaign` therefore refuses
current registration, and `validate-qualification` refuses current admission. These
commands cannot be enabled by supplying an artifact that claims authorization.
`delivery-eval schema --kind campaign` and `--kind arm-configuration` remain available.
The `--kind calibration` schema is the legacy reference-only contract; the executed
calibration API is documented in [development calibration](evaluation-calibration.md).

Existing schema-1 campaign artifacts remain inspectable without spending:

```sh
uv run delivery-eval inspect-legacy-campaign --artifacts /private/frozen-artifacts --campaign-artifact SHA256 --output /private/history-summary.json
```

The output must be outside protected storage. The summary explicitly reports
`current_qualification_verified: false`, `calibration_verified: false`, and
`spend_authorized: false`. Historical readability never upgrades a legacy record.
No qualified historical manifest or completed campaign is bundled with this repository.

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
- Every task passes the current concrete v2 authority against its fully normalized
  manifest, current action grant and actual private ledger evidence. Legacy v1
  structural evidence, reviewer labels and serialized `passed` flags are insufficient.
- This bounded module accepts the executable-behavior qualification profile only. Thus
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

The current calibration gate calls the executed validator through the concrete
qualification authority. It checks current allowlists/expiry and measured decisions
against frozen development fixtures, with actual operation receipts and configured
rubric/model bindings. It does not establish unbiased real-world judge accuracy or
human benefit. Primitive campaign tests explicitly patch the authority boundary to
exercise scheduling, caps and denominator rules; those fixtures are not qualification
or calibration evidence. Real chain validation is tested separately.

The timestamp and `execution_started: false` assertion cannot prove a campaign has
never run. This pure module does not maintain a run registry, authenticate artifact
writers, enforce one-time sealed-set access, reserve money in a live ledger, or
reconstruct the scoring-code commit. A future controller must enforce campaign
uniqueness, phase gates, sealed-set retirement, per-call reservations, cancellation,
candidate freezing, independent final scoring, and artifact access boundaries.
No task results, human effort estimates, or efficacy claims follow from freezing.

## Explicit execution-budget contract

[ADR-014](adr/ADR-014-campaign-execution-budgets.md) adds the separate
`freeze_execution_campaign(...)` API, with the same arguments, returning a schema-3
`ExecutionCampaign`. It preserves admitted task manifests and explicitly uses the
frozen arm limits for builder, review, repairs and final scoring together. This allows
separately metered qualification to have a different budget without changing its
evidence or increasing comparison limits. Schema-2 `freeze_campaign` keeps its
existing exact budget-equality requirement; no record is automatically upgraded.

The new API reuses all corpus, current-authority, calibration, arm-parity, schedule
and campaign-cap checks. Seven owned contract cases and the existing campaign suite
passed together (58 tests); the authority injection remains a test boundary, not a
qualified corpus. Schema 3 still creates no account or execution permission. Its
execution controller and versioned scoring consumer remain required before use.
