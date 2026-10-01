# ADR-012: Owned synthetic calibration preparation

Status: accepted for controlled implementation, 2026-09-28.

## Context

The executed qualifier requires model calibration before its own review stage. Calibration
contexts need actual runtime evidence. Historical preparation expects real issue, license and
accepted-commit provenance; locally authored development toys cannot truthfully supply those
fields. Negative calibration subjects also cannot be mislabeled as safe executable tasks.

## Decision

Introduce explicit project-owned synthetic task, provenance, rights and reference-construction
contracts. They carry a real construction-code revision and exact authored bytes, without
inventing historical issues or accepted solution commits. Preserve historical schemas and gates.
The repository has no declared public license; these fixtures use the internal identifier
`LicenseRef-Project-Owned-Internal`, bound rights text and explicit scoped controller permission.
This is not a public redistribution license or an independent legal determination.

Bind the full authored case digest into the synthetic task, provenance and data authorization.
The private authored case includes separately frozen expectations and a reference implementation.
It cannot be used as model supporting evidence or a rubric. Import writes protected artifacts
and metadata only; current policy, execution permission and budgets remain caller-owned.

Use the existing deterministic runtime to execute five harmless development anchors, each with
preflight and the twelve-run matrix. A shared producer reconstructs review inputs from completed
ledger operations. It requires authentic completion and current rights/configuration, rather than
accepting manually written execution JSON. No model calibration is required to execute this
authorized deterministic prerequisite.

Represent the separate calibration review subject explicitly as inert. Its evidence identifies
the safe execution anchor and has `subject_executed=false`; subject judgments remain pending
until review. Known rejection, ambiguity, high risk and inadequate oracle coverage may be
represented truthfully without executing unsafe behavior. These subjects cannot resolve into
qualification admission. Expected statuses and reference code remain outside model inputs.

Freeze one bounded preparation plan with five distinct accounts and contexts before Docker work.
Account infrastructure ceilings sum within the plan ceiling. The preparation runner has no model
effect path and returns `MODEL_CALIBRATION_NOT_RUN`, with zero model usage and `admitted=false`.
Exact settled runtime effects resume; unknown reservations cannot be silently retried or aliased.

Share exact request construction between the model broker and a pure reservation forecast.
The forecast reads no credentials, contacts no provider and returns only digests, serialized
length and reservation metadata. Actual usage still comes from provider receipts. A later
model-calibration run needs its own current finite grant and cannot infer permission from a
successful preparation result.

## Consequences

The five authored cases form one development family, not five independent historical tasks.
They exercise protocol and judge behavior without qualifying the historical catalog or proving
production model accuracy. Live calibration, a fresh non-admitting synthetic qualification run,
historical rights/oracle qualification, campaign execution and release gates remain distinct.
Human plan approval, merge authority and pilot signoff remain unchanged.

See [synthetic preparation](../synthetic-preparation.md), [protected import](../synthetic-import.md),
[review-input production](../qualification-inputs.md), [calibration subjects](../calibration-subjects.md),
[authored cases](../synthetic-calibration-cases.md) and [request forecasting](../model-request-forecast.md).
