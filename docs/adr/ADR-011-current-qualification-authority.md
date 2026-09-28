# ADR-011: Executed qualification and current consumption authority

Status: accepted for controlled implementation, 2026-09-28.

## Context

ADR-007 establishes automated benchmark qualification and ADR-010 defines protected executed
stages. Independently constructed review JSON cannot prove that those stages ran. Conversely,
an authentic completed execution should not become fictitious merely because its original
execution window expired. Later use needs current permission and current policy validation.
Qualification also cannot implicitly authorize unmetered candidate scoring.

## Decision

Use a single private qualification controller to execute the frozen deterministic matrix and
independent model reviews, with conditional adjudication. Persist actual operation receipts,
immutable checkpoints, timestamps and closed accounting in the separate evaluation ledger.
Keep reference solutions out of model contexts and all protected evidence out of worker export.

Require the concrete controller-owned `QualificationAuthority` for current worker export,
scoring and campaign preregistration. The authority reconstructs the entire executed chain,
including calibrated model configuration, chronology, per-operation bindings and exact spend
totals. Historical completion is checked against trusted ledger timestamps inside the original
execution grant. Current data rights, configuration, calibration policy and an action-scoped
current-use grant are checked at consumption. Arbitrary task artifacts cannot supply authority.

Use `independent-agents-v2` for current admission. Retain explicit read-only inspection of v1
qualification and campaign records; they no longer authorize current execution or export.
Offline CLI commands cannot manufacture a trusted authority. A trusted loader and campaign
execution controller remain future work.

Require a distinct scoring account and grant bound to the qualified task, candidate, settings,
policy, rate card and deadline. Meter preflight, acceptance and regression separately. Current
qualification permission and scoring permission are rechecked during execution. Settled exact
operations can resume; unknown reservations cannot be retried automatically.

Synthetic validation is explicitly non-admitting. Tests and controlled responses are software
verification evidence, not historical qualification, measured model calibration or benchmark
results. Human plan approval, merge authority and pilot signoff are unchanged.

## Consequences

Legacy artifacts remain inspectable without silently acquiring new authority. More evidence
must be retained privately, and authority providers, artifact writers and the ledger remain
trusted components. Closed qualification accounts cannot be reused for later work. Account
caps bound individual executions; campaign-wide allocation is not yet implemented. Calibration
and semantic quality still require actual authorized development and historical executions.

See the [controller](../qualification-controller.md), [admission](../qualification-admission.md)
and [scoring](../scoring-execution.md) contracts for implemented APIs and tested limits.
