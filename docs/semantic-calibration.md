# Executed owned final-scoring calibration

`evaluation/semantic_calibration.py` executes five explicitly authorized development
model operations through the real structured-model broker and a dedicated evaluation
ledger account. Its purpose is `OWNED_FINAL_SCORING_CALIBRATION`, separate from
qualification calibration. Existing qualification schemas, prompts and consumers are
unchanged. A passing record is not historical admission, historical scoring permission,
campaign execution permission or a benchmark result.

## Inputs and public API

- `SemanticCalibrationSpec` pins exactly five distinct fixture IDs, context artifacts
  and separate expectation artifacts, plus the rubric, `semantic_prompt(rubric)`,
  output schema, model configuration and evidence-validity interval. It requires the
  five owned categories: correct, requirement gap, hardcoding, harness gaming and
  unresolved. The expected map must exactly cover every criterion and all three
  integrity checks; category-specific mandatory failures cannot be replaced by PASS.
- `SemanticCalibrationPolicy` is a current trusted exact-spec/model allowlist with
  authorized issuers and maximum budgets. `SemanticCalibrationAuthorization` binds
  one dedicated `semantic-calibration:` account, exact spec/configuration, a finite
  validity interval and at most 1,800 seconds of execution from its original issue
  time. The policy must permit the grant's complete budget; repair rounds are zero.
- `run_semantic_calibration(spec_artifact, *, authorization_provider,
  policy_provider, artifacts, expectations, authorities, ledger, model, clock)`
  returns the immutable result artifact. `authorities` maps each fixture ID to its
  concrete `OwnedSemanticContextAuthority`; five distinct owned runtime accounts
  and subjects are required. A supplied callback asserting validity is insufficient.
- `validate_semantic_calibration(evidence_artifact, *, expected_spec_artifact,
  authorization_provider, policy_provider, config, artifacts, expectations,
  authorities, ledger, clock, require_pass=True)` reconstructs the record read-only.
  `require_pass=False` permits inspection of measured failed calibration, not promotion.

The context authority reconstructs [actual owned runtime evidence](owned-semantic-context.md).
Missing, failed, unknown or altered deterministic receipts stop processing before a
model call. The unresolved anchor has incomplete *semantic requirements*, not missing
execution provenance. No fake `HistoricalTask` or historical qualification authority
is created for these subjects.

Subjects and [authored expectations](semantic-scoring-examples.md) remain separate.
The calibration and expectation artifact roots must be disjoint and outside all
owned worker roots. The SQLite ledger must also be outside those worker roots.
The caller still owns private storage and host access controls; a digest is not an
authorization or an attestation of the source's truth.

## Finite operations and resume

Before account creation, the controller validates all five current contexts and
expectations and computes exact reservation forecasts for the five fresh invocation
contexts. Their model cost, input and output ceilings must fit the one grant. The
plan freezes five distinct context IDs, five operation IDs, account, grant, spec,
artifact roots and original deadline in a durable ledger checkpoint before calls.
Actual per-call reservations are atomic; the five reservations are not one batch
transaction. No sixth call, repair, retry alias or extra account is created.

The current grant must equal the original grant. Policy, model configuration and
concrete context authority are rechecked before, during and after model work. An
absolute timeout and the shared guarded cancellation helper retain ownership of
cleanup; uncertain provider calls retain their conservative reservation. Any UNKNOWN
operation prevents automatic resume, including when policy becomes permissive again.
Completed settled operations are read and verified without invoking the broker or
looking up a provider key. Partial resume keeps the original plan and deadline;
changing or extending a grant cannot rebind it. A completed record may be consumed
after the execution window only while its original evidence/grant validity and
current policy/context authority remain valid.

Every settled broker output is bound to the exact prompt, context, schema, model
configuration, rates and forecast reservation. The reader compares the saved
operation document with the ledger, verifies provider response identities are unique,
and reconstructs plan/case/result checkpoint and operation chronology. It recomputes
token/cost totals and requires exactly the five planned operations, zero outstanding
reservation and exact account totals. Costs use the configured rate card, not a
provider invoice. This account covers model calibration only; separate owned Docker
preparation costs remain in their original runtime accounts.

## Meaning of the result

`CALIBRATED` requires five structurally valid outputs, five exact finding-map and
verdict matches, zero false-ready responses and zero mandatory failures. Requirement
gap, hardcoding and harness-gaming cases are mandatory false-ready controls. Any
disagreement, invalid citation or duplicate finding in an otherwise parsed and
settled output remains charged and produces `CALIBRATION_FAILED`; it is never
reissued to improve the score. Malformed provider output that the broker cannot
settle remains UNKNOWN and yields no completed calibration record.

The prompt requires exact criterion/integrity coverage and candidate, baseline,
oracle and observed-receipt citations appropriate to each finding. Structural
validation checks coordinates and coverage, not whether the prose is insightful.
Expected labels, diagnostic counterexamples and other reviewers' verdicts never
enter the model context. These are single independent initial scorer invocations,
not the later two-pass historical scoring/adjudication procedure.

The tests use actual owned runtime ledger/receipt chains and controlled HTTP through
`StructuredModel`. An optional Docker case executes all five subjects before those
controlled model responses. These tests validate accounting, bindings and rejection
paths; scripted responses do not establish a live model's judgment accuracy. No live
paid calibration or historical scoring is claimed by this implementation.

```sh
uv run --no-sync python -m pytest tests/test_semantic_calibration.py -q
```

The Docker case requires a previously built immutable `TEST_SANDBOX_IMAGE`; it
explicitly skips when unavailable. No test uses a real provider credential or network.
