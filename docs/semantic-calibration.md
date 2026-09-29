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
paths; scripted responses do not establish a live model's judgment accuracy. Live development calibration outcomes are recorded below; the test suite itself
claims no paid execution or historical scoring.

```sh
uv run --no-sync python -m pytest tests/test_semantic_calibration.py -q
```

The Docker case requires a previously built immutable `TEST_SANDBOX_IMAGE`; it
explicitly skips when unavailable. No test uses a real provider credential or network.

## First live development attempt

On 2026-09-28 the controller froze five original contexts, separate expectations,
rubric, prompt, schema and an Opus 5 configuration before authorizing a finite
five-call run. Exact worst-case reservation was 2,792,015 microdollars, with 58,403
upper-bound input tokens, 100,000 output tokens and an original 1,800-second deadline.
The first two calls settled at 240,050 microdollars (9,235 input and 7,755 output
tokens). The third returned HTTP 400 without usage metadata, retaining a 558,270
microdollar reservation. Execution stopped; no retry, completed calibration or
historical scoring authority followed.

A separately authorized one-call capability diagnostic used only a small original
input and retained an immutable plan. It also returned HTTP 400, with an allowlisted
`invalid_request_error` and a billing/spending-limit text hint. Its 20,495 microdollar
reservation remains unresolved. The hint does not determine the earlier call's
cause or establish a zero charge. No raw provider error text or credentials were
published. [Provider documentation](https://platform.claude.com/docs/en/api/errors)
allows multiple causes for HTTP 400, including configured spending limits.
Both original accounts are retained unchanged. Later capacity restoration does not
settle their unknown reservations or change the original failed outcome.

## Subsequent completed development calibration

After the user reported billing restored, a separately bounded one-call diagnostic
returned HTTP 200: 279 input tokens, 11 output tokens and 1,670 microdollars, with
zero remaining reservation. It supplied no calibration authority.

On 2026-09-29 UTC, a fresh five-case run at source `48bb0de` retained the original
owned runtime evidence, expectations, rubric, prompt and 20,000-output model
configuration. New immutable context/operation identities and a separate finite
grant reserved at most 2,792,015 microdollars on the original ledger. All five calls
settled, using 23,287 input and 19,251 output tokens for 597,710 microdollars.
Read-only validation and cached recovery left the ledger unchanged and no reservation.

The result was **CALIBRATION_FAILED**: all five overall verdicts matched, but only
three outputs were structurally valid exact finding-map matches; two mandatory
controls failed the required structural checks. The observed false-ready count was
zero. A read-only fixed-code diagnostic reported one out-of-range file citation and
two missing acceptance-node citations across the two invalid outputs. No output
prose, source bytes or expected labels were exposed by that diagnostic. These
formatting failures remain failed calibration evidence, not corrected model results.

The evidence reference is `dd479e1789600e7271cf09ae7a2601298e453d0f4213cb842a8c302fb7573fea`.
The original partial run and failed diagnostic remain separately retained, including
their unresolved reservations. No final scorer is calibrated by this run and no
historical scoring is authorized. Future prompt changes require distinct frozen
artifacts and a new calibration; the original prompt must remain reconstructable.

Separately, this development profile cannot reserve two 20,000-output scorer calls
inside the campaign's 20,000-output total attempt ceiling. Before any campaign, a
compatible preregistered per-call configuration and context profile must pass fresh
calibration and all existing total budget checks. No cap is raised by this result.
