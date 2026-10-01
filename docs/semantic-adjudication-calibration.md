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

`adjudication_calibration_prompt(rubric)` preserves the exact owned-only v1 prompt.
`executed_adjudication_prompt_v2(rubric)` provides a prospective shared executed-evidence prompt
with provenance-conditional instructions. `resolve_adjudication_prompt(rubric, prompt_bytes)`
accepts only exact v1 or v2 bytes; the pinned spec selects the version, with no implicit upgrade.
Both apply the same structural output schema, target-specific citation rules and frozen
expectations. Prompt bytes, rubric, configuration and exact request bind every operation.

The v2 prompt distinguishes owned executed evidence with authored hypothetical peers from
historical evidence with initial model-review references. It never treats serialized claims as
authority. Owned calibration retains its existing truthful purpose and input contracts unchanged;
a historical executor must use a distinct historical purpose and reconstruct actual initial
review receipts. These are different context profiles with a common `context` and
`disputed_findings` projection shape, not identical inputs. Owned calibration measures the
authored dispute cases only; historical provenance, qualification and current authority require
separate controller validation. V1 evidence cannot qualify a historical v2 execution.

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

## Recorded live owned calibration

On 2026-09-29, prospective run v44 passed all five original owned cases at source
`d00cafff367f30d0f76640a925a2a2ab8f09fb99`. It used the shared v2 prompt and the same
Opus 5.5/6,000-output configuration as the passing initial-scorer calibration. The
[fixed-tuple wire projection](anthropic-tuple-schema.md) changed generation syntax only;
the original output contract, rubric, authored peers, expectations and validators remained
unchanged. Runtime evidence was reconstructed from the original actual owned executions.

| Bound evidence | Value |
| --- | --- |
| Specification | `1ad5ebbf981005eb4124eb704235c83673aa2a288378a720e98a9b5a6e510fe5` |
| Result | `21c154d88df0a4edea684d23062eae3ff2c9e4f3fcb11e6261d8ee52448fd789` |
| Configuration | `39f84911608c87fd8c11820b116b257bd7a8d78f96b83d77ab347b04b966b91d` |
| Prompt | `cb9b66c148f4dc60346c5b5774f46b3b729226cbb40d962a82c0b18cf34f6f67` |
| Rubric | `5b8a7a093755a1b9ad21af411cf414a9ffad01980fda629c1c2b4f17b8183899` |

The finite grant allowed five calls, 127,602 upper-bound input tokens, 30,000 output tokens,
1,110,408 microdollars and 1,800 seconds. Execution ran from 01:40:37.151662 to
01:42:43.562615 UTC. All five operations settled: 52,826 reported input tokens, 8,457
output tokens and 380,444 microdollars ($0.380444), with zero remaining reservation.
All five outputs, exact dispute maps, complete cases and merged verdicts matched; there
were zero new concerns, mandatory failures or false-ready observations. Cached recovery
preserved the same evidence and accounting with no new calls. Current required-pass
readback also succeeded with artifact writes, account creation, checkpoint writes,
reservation and settlement forbidden, and unchanged account totals.

The earlier v41 first call returned HTTP 400 with unknown usage and retains its 218,940-
microdollar reservation. Separate schema-only diagnostic v42 reported unsupported
`prefixItems`, also with unknown usage; its 136,664-microdollar reservation remains.
Neither operation was reissued or retrospectively converted into zero-cost success.
V44 is a separately frozen corrected wire request, not a rewrite of those failed records.

This is passing calibration for five owned dispute anchors. It establishes neither
historical task admission nor held-out judge accuracy, campaign success or permission
to spend on historical adjudication. Current runtime/calibration authority and a separate
exact historical execution grant remain required at consumption.
