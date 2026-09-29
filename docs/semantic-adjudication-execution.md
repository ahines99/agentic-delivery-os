# Sealed historical-review adjudication

`semantic_adjudication_execution.py` implements one separately authorized third model operation
after two valid initial semantic reviews disagree on target statuses. It consumes their existing
`SemanticExecutionEvidence` and creates a separate immutable adjudicated result. The initial
result, review records, contexts, model receipts and authority records remain unchanged. An
agreement, invalid initial review or deterministic failure cannot enter this continuation.

This is controller implementation, not evidence that a historical task has been scored. Controlled
tests use project-owned fixtures and explicitly substituted admission/calibration authorities,
with actual model-broker requests, receipts and accounting against local controlled transports.
No paid model calls or historical inputs are necessary for those tests.

## Authority and experimental conditions

`HistoricalAdjudicationExecution` requires a concrete `SemanticExecution` and a separate concrete
`AdjudicationCalibrationAuthority`. The latter reconstructs the five-case owned adjudication
calibration through its current authority; initial-scorer calibration cannot substitute. The
adjudicator configuration must equal the initial configuration, which remains bound to the frozen
campaign arm. Introducing a role-specific model would require a new preregistered arm protocol.

A current `HistoricalAdjudicationAuthorization` binds the original result and plan, original
semantic/scoring authorizations, account, candidate, deterministic evidence, qualification,
adjudication calibration spec/evidence, rubric, prompt, output schema and model configuration.
Policy approves the exact grant digest and issuer. Qualification, repository model-data
authorization, both calibration authorities and all original spending grants remain current.

Historical execution accepts only the exact shared executed-adjudication prompt v2. The owned
calibration uses actual owned runtime evidence with authored hypothetical peers; historical input
uses actual initial model-review receipts. These distinct profiles share the generic prompt,
output contract and deterministic dispute/reference projection. The owned calibration is not a
claim of identical contexts or historical judge accuracy.

## Reconstruction and merge

The controller reconstructs both original reviews through `validate_semantic_scoring`, then binds
their exact context IDs/artifacts, review records, operation artifacts/IDs, provider response IDs
and findings into `HistoricalAdjudicationContextClaim`. Its serialized authority flag remains
false: parsing a claim does not authenticate it. `HistoricalAdjudicationInput` supplies the exact
computed disputed keys and original peer finding digests, with a fresh third context identity.
No expected answers, reference implementation or repair feedback enter this envelope.

The structural merger permits exactly the genuinely differing targets. It preserves agreed
statuses, requires both exact peer references and target-specific source/receipt citations, and
retains new concerns as blockers of a would-be PASS. A parsed but structurally invalid response
produces an immutable `INVALID_ADJUDICATION`/`UNRESOLVED` result. There is no repair call.
The completed result records third-operation token/cost metrics; original review metrics stay in
the original result and the account retains the complete attempt totals.

## One original account and deadline

The controller never creates an account. The third request must fit the remaining model cost,
total cost, input-token and output-token limits on the original attempt. The immutable plan pins
every settled preceding operation, one fixed third operation ID, both exact context/input
artifacts and a deadline no later than the original initial/scoring/attempt deadlines. Changing
grants or extending expiry cannot renew a partial plan. RESERVED/UNKNOWN operations stop without
reissue; a settled operation can resume finalization after interruption.

The original initial-review validator remains closed by default. A private continuation scope
allows only this exact third operation after authenticating the concrete controller, owning
thread/task, immutable plan/checkpoint, settled prefix digests, reservation and complete account
totals. Copied child-task context provides no authority. Campaign reservation guards recognize
this proof only for the same scoring execution. No caller-supplied extra-operation flags or
filtered ledgers are accepted.

`validate_semantic_adjudication` performs current read-only reconstruction of the separate result,
all original evidence, the third receipt and chronological checkpoints. It does not write
artifacts, reserve funds or call models/runtime. Like the current historical scoring authority,
validation requires unexpired original authorization; it does not provide a deadline-renewing
readback mechanism. Stored evidence remains inspectable data after authority expires.

```python
result_artifact = await run_semantic_adjudication(
    initial_result_artifact, execution=adjudication_execution, model=structured_model
)
evidence = validate_semantic_adjudication(result_artifact, execution=adjudication_execution)
```

These APIs do not publish results, authorize merges, feed judgments back to a builder, or change
the campaign's original evidence. A downstream campaign aggregator must explicitly consume the
validated separate adjudicated result; merely finding it in storage grants no authority.
