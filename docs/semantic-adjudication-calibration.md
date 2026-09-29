# Executed owned adjudication calibration

`semantic_adjudication_calibration.py` implements a separate five-case calibration runner and
read-only completed validator. It consumes `ExecutedOwnedAdjudicationContext` through concrete
`OwnedAdjudicationContextAuthority` instances. Each context binds actual owned candidate runtime
receipts to the original authored peer hypotheses. Those peers remain hypothetical judgments;
they never acquire provider identities or count as independent initial scorer operations.

This calibrates the adjudication contract only. It does not authorize historical scoring,
adjudication, campaign execution, admission, merge, or a model call merely because fixtures exist.
No live model accuracy or historical result is claimed by controlled-response tests.

## Separate authority and immutable inputs

The spec, policy, authorization, plan and evidence use `OWNED_ADJUDICATION_CALIBRATION` and the
account prefix `adjudication-calibration:`. Initial-scorer calibration records and authority
objects cannot substitute. Current policy pins exact spec and model-configuration digests and
issuer identities; the grant binds the spec/configuration, finite budget, issuance and expiry.
Current runtime and rubric authorities are revalidated throughout execution and readback.

The spec contains exactly five distinct context references and five separate expectation
references. The loader requires the exact bytes of the five original
`AuthoredAdjudicationExpectation` records and original authored peer contexts. Caller-supplied
replacement expectations do not become valid merely by updating an allowlist. Expectations live
in a disjoint private store outside authored/runtime/model artifact trees and worker roots.
Private context artifacts and the dedicated evaluation ledger also remain outside worker roots.

`adjudication_calibration_prompt(rubric)` produces one exact purpose-specific prompt. It builds
on the adjudication structural contract and explicitly applies execution-receipt citation rules
to executed owned contexts. The schema and prompt bytes, rubric, configuration, and exact request
are bound to every operation. Unknown or modified prompt bytes are rejected; no implicit version
upgrade occurs.

## Model input and structural merge

`adjudication_model_input(context)` returns a typed envelope containing only the unchanged
executed context and deterministic disputed target/peer-finding references. The controller hashes
each original peer finding; models copy those references rather than computing SHA-256. The
projection contains no expected category, verdict, resolution map or expectation artifact.
`validate_adjudication_model_input()` rejects altered, missing, extra or reordered projections;
it checks derivation, not runtime authority. Every request forecast and receipt binds the exact
serialized envelope.

The existing `merge_adjudication_structure()` requires precisely the disputed targets, both
peer references, valid target-specific citations, and immutable agreement statuses. New concerns
must cite existing targets; they block a would-be passing verdict without rewriting agreement.
Calibration counts these concerns explicitly. The frozen examples expect no additional concern,
so adding one cannot become an exact match even if another failing finding already makes the
merged verdict fail. Structurally invalid but parsed outputs remain measured failures with their
settled costs; schema-invalid or uncertain provider responses retain reservations and stop.

## APIs and measurements

```python
reference = await run_adjudication_calibration(
    spec_artifact,
    authorization_provider=current_grant,
    policy_provider=current_policy,
    artifacts=private_artifacts,
    expectations=private_expectations,
    authorities=context_authorities,
    ledger=evaluation_ledger,
    model=structured_model,
)
evidence = validate_adjudication_calibration(
    reference,
    expected_spec_artifact=spec_artifact,
    authorization_provider=current_grant,
    policy_provider=current_policy,
    config=model_configuration,
    artifacts=private_artifacts,
    expectations=private_expectations,
    authorities=context_authorities,
    ledger=evaluation_ledger,
)
```

The runner forecasts all five requests before creating its account. All must fit the authorized
model, input-token and output-token ceilings. It freezes fresh context/operation identities and
one absolute execution deadline. Plans/checkpoints and exact returned operations are immutable.
Restart reuses settled operations; RESERVED/UNKNOWN operations cannot be retried under new IDs.
Cancellation retains accounting and waits for the underlying transport cleanup. Active checks
also detect policy/configuration/runtime revocation; already issued work may incur cost.

Metrics recompute valid structural outputs, exact disputed maps, merged-verdict matches, exact
cases, added concerns, false readiness, three mandatory safety-case failures, reported tokens,
and configured rate-card cost. `CALIBRATED` requires all five cases to match exactly, no false
readiness and no mandatory failure. A complete incorrect run returns `CALIBRATION_FAILED`;
diagnostic readback uses `require_pass=False`, without granting authority.

Readback reconstructs current inputs, frozen plan/grant/store bindings, request reservations,
unique provider responses, checkpoint chronology, and closed account totals. It neither writes
artifacts nor creates accounts or executes models/runtime. Completed evidence may be read after
the execution deadline while its validity and current authorization remain effective; changing
or extending the frozen execution grant cannot repair an expired partial run.

Unit/contract tests use the actual broker and evaluation ledger with explicitly controlled model
transports and runtime fixtures. The opt-in Docker test uses real owned runtime checks plus the
same controlled model responses; it does not spend provider money or establish judge accuracy.
Production storage/controller integrity and semantic correctness remain external trust limits.
