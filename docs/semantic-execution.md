# Two independent final candidate scorers

`evaluation.semantic_execution` implements two initial model reviews after current,
passing campaign deterministic scoring. It does not allocate a campaign, create an
attempt account, build a candidate or authorize adjudication. No historical task
has been semantically scored by this implementation's controlled tests.

`SemanticExecution` requires the concrete current `QualificationAuthority` and
`CampaignScoringExecution`, the sealed candidate artifact, a current explicitly
allowlisted `SemanticExecutionAuthorization`, and a concrete
`SemanticCalibrationAuthority`. The latter reconstructs all five owned calibration
cases, actual provider receipts, original grant, current policy and original owned
runtime authorities through `validate_semantic_calibration`; a supplied summary
claim or qualification-purpose calibration is insufficient. Owned calibration
remains evidence about the initial scorer, not historical data or spending authority.

The historical scoring grant pins the campaign scoring authorization digest, exact
completed deterministic evidence, candidate, final-scoring calibration/spec, rubric,
prompt, output schema and model configuration. It must fit the existing attempt's
original deadline. The model must match the frozen campaign arm, and its broker must
use that attempt's existing evaluation ledger. Both independent forecasts must fit
remaining model, token and shared total ceilings before the first call. Actual
reservations remain per operation; no new capacity or batch reservation is minted.

## API and evidence

```python
reference = await run_semantic_scoring(execution=execution, model=structured_model)
evidence = validate_semantic_scoring(reference, execution=execution)
```

The immutable plan checkpoint freezes exactly two contexts and operation identities,
current grant/policy, original deadline, private artifact root, and every pre-existing
account operation digest. Both contexts have empty peer reviews and the same frozen
evidence. They have distinct context IDs and stages. No expected calibration label,
prior review output or reference solution is appended to either initial context.

Each result is accepted only with the real broker's settled operation receipt. The
reader reconstructs exact context, prompt, schema, provider, requested model, rates,
reservation, token/cost totals, output and checkpoint chronology. Provider response
identities must differ. Required criterion and integrity findings must contain valid
candidate, baseline, oracle and observed execution citations as appropriate.

Two valid matching finding-status maps produce `AGREEMENT`. Only agreement on `PASS`
under current authority yields `strict_success=True`. Agreement on `FAIL` or
`UNRESOLVED` remains unsuccessful. Different finding-status maps produce
`DISAGREEMENT` and `UNRESOLVED`, even when overall verdict strings coincide.

A parsed and settled output with invalid coverage/citations becomes `INVALID_REVIEW`;
its charge remains recorded. An invalid first review stops before the second call.
Malformed provider output, cancellation or uncertain transport retains UNKNOWN
reservation state and yields no completed semantic evidence. No replacement operation
or adjudication is attempted. This initial five-case calibration does not authorize
a different adjudication prompt/schema or an adjudicated success claim.

Completed and partial settled recovery use the same plan, contexts, IDs and deadline.
Missing operation rows cannot be reconstructed by calling the provider again when
case/final checkpoints or original account totals show prior effects. Any unrelated
pending operation also denies scoring. Completed readback is current authority
validation, not an archival success API; expiry or revocation denies cached use.
All evidence stays evaluator-only and nothing is routed back into builder repairs.

## Active reservation boundary

The default public completed-scoring reader still requires an idle account. A fresh
semantic invocation first proves current authority and the absence of its operation.
Only its synchronous polling guard installs a private `ContextVar` lease. The lease
binds the immutable plan checkpoint, exact invocation, account, forecast ceilings
and owning asyncio task. It cannot excuse an existing UNKNOWN operation on resume.

The guard accepts only that exact active reservation; every prior operation remains
unchanged, account aggregates must reconcile, and unrelated UNKNOWN operations deny.
The reserved row alone is not provider-request attestation: the immutable plan binds
the pending request, while the eventual broker receipt must prove its actual request
digest. The lease is reset after each synchronous guard and invalidated in `finally`.
Copied child-task contexts fail the owner-task check. Public readers outside this
private guard remain idle-only, including while the provider request is running.

The guard refreshes current campaign, qualification, semantic authorization,
calibration and context authority before, during and after work. Cancellation uses
the existing owned-cleanup join; an uncertain model reservation is never released by
the controller. Calibration artifacts, expectations and SQLite ledger must also
remain outside the historical worker and configured repositories.

## Validation boundary

Tests use owned, explicit substitutions for historical qualification/context and
controlled Docker reports, while exercising the real campaign guard, immutable
ledger, request serialization and `StructuredModel` with controlled HTTP responses.
A separate test reconstructs a genuine five-owned-case controlled calibration chain
through the concrete calibration authority. These establish machinery and rejection
behavior, not live model accuracy or historical scoring results. No paid provider
call is made by the suite.

```sh
uv run --no-sync python -m pytest -q tests/test_semantic_execution.py
```

Related: [semantic calibration](semantic-calibration.md),
[protected scoring contexts](semantic-scoring-context.md), and
[campaign deterministic scoring](campaign-scoring.md).
