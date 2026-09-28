# Bounded synthetic preparation without model calls

`evaluation.synthetic_preparation_runtime.run_synthetic_preparation` prepares exactly five
project-owned development examples for later calibration. It executes each safe anchor's
preflight and twelve repeated deterministic checks, materializes runtime-verified private
evidence, and assembles one protected qualifier context for the corresponding inert subject.
It does **not** call a model, calibrate a model, admit a historical task, export campaign input,
or assert that a subject's riskier or ambiguous request was executed.

## Frozen plan and trusted inputs

`SyntheticPreparationCase` contains the validated `ImportedSyntheticExample`, frozen
`DeterministicRequest`, original `RuntimeAuthorization`, six evidence references, six
`EvidenceSummary` findings, and a fixed context ID. `SyntheticPreparationPlan` contains exactly
five cases, a rubric artifact, an infrastructure ceiling, and absolute issue/expiry times.
Its fixed labels are `model_calls="NO_MODEL_CALLS"` and `calibration_status="NOT_CALIBRATED"`.

Example, task, account and context identities must be distinct. The protected authoring
records must cover all five calibration categories once. Categories and expected judgments
stay in protected authoring data; they do not become model-visible answer hints. Each actual
task must be a `SyntheticTask` with development split, honest project-owned provenance and
an exact authoring/import/request binding. The bounded UTF-8 rubric is checked before work.
Current preparation policy must explicitly approve each imported data authorization.

The infrastructure ceiling must cover the sum of all five declared account infrastructure
ceilings. Every task's model microdollar, input-token and output-token budgets must equal one,
the existing budget contract's minimum. These minimal terms are not model-call authorization.
There is no broker invocation in this runner, and any model usage or unrelated ledger operation
prevents a successful result. Infrastructure accounting uses zero model tokens.

The trusted caller supplies fresh settings/policy callbacks, private input/output artifact
stores, a disjoint worker root, a separate evaluation ledger, and the current UTC clock:

```python
result_artifact = await run_synthetic_preparation(
    plan,
    settings_provider=load_current_settings,
    policy_provider=load_current_preparation_policy,
    protected_artifacts=protected,
    output_artifacts=output,
    worker_root=worker_root,
    ledger=ledger,
)
```

Before external effects, the complete immutable plan artifact is checkpointed under
`synthetic-preparation-plan-v1` in **every** account. A changed plan cannot borrow the same
accounts. The caller is responsible for provisioning and explicitly authorizing the finite
run; plan objects or account creation do not establish legal rights or operator approval.

## Execution, accounting and recovery

The existing deterministic runtime owns operation bindings, conservative infrastructure
reservations, absolute per-case execution deadlines, collector checks, and cleanup. The
wrapper additionally checks its plan expiry and current policy/scopes before and after each
runtime and while awaiting work. Policy changes or expiry cancel the retained child and await
cleanup. Both stores and the SQLite ledger remain outside worker/configured repository scopes.

Settled runtime operations resume through their original IDs without another Docker call.
Unknown operations retain their reservations and cannot be automatically reissued. Resume
requires the original plan and execution windows to remain valid; the runner never creates
replacement account aliases or extends a grant. Partial account/checkpoint writes remain
visible after failure, with no automatic release or claim of batch atomicity.

For each completed case the runner reconstructs a qualification input from the trusted
runtime ledger, binds the authored review subject to that exact safe anchor, and assembles
an evaluator-only `qualifier_a` context. Reference implementations and expected decisions
remain excluded from the review projection under the existing context assembler's contract.
Protected context contents are not appropriate for interactive implementation-agent output
or campaign builder/reviewer input.

Completion requires exactly thirteen settled infrastructure operations per account, no
unknown or unrelated operations, zero model usage, and consistent actual infrastructure
estimates. The result is stored in the protected artifact store and checkpointed as
`synthetic-preparation-complete-v1` in every account. Its fixed status is
`MODEL_CALIBRATION_NOT_RUN`, with `admitted=false` and zero model cost/tokens. Each case
contains private runtime/input/subject/context references, thirteen accounting receipt
digests, and actual infrastructure estimates. Those local rate/time estimates are not a
provider invoice or benchmark score.

## Validation boundary

Focused tests use the actual project-owned importer, real SQLite accounting, actual evidence
materialization and context assembly, with an explicitly controlled collector replacing Docker.
They exercise all sixty repeated checks plus five preflights, exact resume, frozen plan and
budget denial, authoring/category/rubric mismatches, private scopes, unknown/unrelated operations,
and active expiry/revocation/cancellation cleanup. Model generation is patched to fail if called.
These tests establish software boundary behavior; actual Docker execution is a separately
reported integration run. Neither constitutes completed model calibration or historical
qualification.
