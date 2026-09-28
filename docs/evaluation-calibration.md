# Executed development calibration

`evaluation/calibration.py` implements a bounded calibration runner and evidence
validator. It exercises the same protected `ReviewContextV2`, `ReviewOutputV2` and
`qualifier_prompt(rubric_text)` used for qualification review. It does not admit a
historical task, run the benchmark campaign, authorize a merge or override deterministic
tests. Existing campaign metadata still reports calibration as unverified until an
explicit integration consumes and validates this executed evidence.

## Frozen inputs and explicit authority

A `CalibrationSpec` identifies one immutable rubric, exact constructed prompt, model
configuration, output schema and five to 32 frozen development fixtures. Each fixture
contains a protected context template, expected verdict and expected status for every
eligibility target and acceptance criterion. Required categories are known admit,
known reject, known unresolved, safety and false admission. The safety case must expect
risk failure; the false-admission case must expect oracle failure. Missing categories,
ambiguous targets, changed prompt/schema/rubric and validation/sealed-test contexts fail
before a provider request.

The runner reconstructs each context's actual source, oracle, support documents and
twelve deterministic receipt projections using the qualification v2 validator. It refuses
initial contexts with peer reviews or an adjudicator role. This checks evidence identity
and structure, not the semantic correctness of a development fixture's expected decision.

Fixtures do not grant themselves authority by labelling their split or category.
`CalibrationPolicy` is supplied by the trusted controller and allowlists exact frozen
spec digests, model-configuration digests, issuers and maximum budgets. A separate,
explicit `CalibrationAuthorization` names an account, that exact spec/configuration,
the budget, issued/expiry times and permission to make model calls on this protected
material. Approval must cover data rights and model processing, not just dollar spend.
Allowlisting a corpus is an operator/controller decision; this module supplies no legal
clearance, cryptographic issuer attestation or automatic fixture qualification.

The controller must supply a current policy provider, not derive an allowlist from the
submitted spec or model output. Policy/configuration/expiry are rechecked between calls
after each call's effect has been retained, and before the final checkpoint and evidence
validation. Removing approval stops later requests and blocks a completed last call
from establishing calibration. An already
issued request may finish or incur cost before revocation is observed.

## Execution, checkpoints and measured results

`run_calibration(spec_artifact, *, authorization, policy_provider, artifacts, ledger,
model, clock)` returns a private evidence artifact digest. `ledger` must be the separate
`EvaluationExecutionStore`, and the supplied `StructuredModel` must use that exact
ledger. The runner creates an immutable account under its authorized cap, freezes fresh
context IDs and operation IDs in a plan checkpoint, then invokes the real adapter once
per fixture. Expected verdicts/statuses remain outside the model context. Other contents
match the frozen fixture template; only the context ID changes.

Each settled operation is read from the ledger and saved as a protected artifact with
an immutable case checkpoint. A restart recovers the same plan and operation IDs. A
settled operation can return its original output without another provider call or new
timestamp. A RESERVED/UNKNOWN operation blocks progress; creating a different ID to
avoid that reservation is not a supported retry. A crash after settlement but before
the case checkpoint can recover the existing operation. Completed results return the
same artifact on resume, including failed calibration results.

The model/token caps apply through the ledger, and an absolute execution deadline is
derived from the original plan's wall budget; restarting does not reset it. Evidence
expiry is the earlier of authorization expiry and the spec's validity interval, at most
seven days. An execution deadline is separate from the later evidence-validity window.

Results contain measured case totals, structurally valid outputs, matched decisions,
fully matched cases, false admissions, mandatory-case failures, actual reported input/
output tokens and calculated model cost. They are recomputed from validated per-call
receipts, exact provider/requested-model/rate-card and context/prompt/schema/configuration
bindings and complete target-level
findings. A structurally valid but wrong agent decision becomes a measured failure.
Provider response object identities must be unique across the run; several operation
IDs carrying the same response cannot count as independently observed cases.
Missing citations or incoherent findings also count as failed output validation. A
schema-invalid or otherwise uncertain provider response retains its reservation and
stops the run without fabricating a completed calibration.

`CALIBRATED` requires every frozen case to match, zero false admissions and zero
mandatory-case failures. Otherwise a complete run records `CALIBRATION_FAILED`.
`validate_calibration(evidence_artifact, *, expected_spec_artifact, artifacts, ledger,
config, policy, now)` requires a current passing result by default. Its diagnostic
`require_pass=False` option exposes recomputed failed measurements; it grants no
admission. Validation checks current checkpoints and receipts, so an arbitrary JSON
boolean or copied summary is insufficient. Changes to configuration, rubric, prompt,
fixture contents or expectations produce a different frozen binding and require an
explicitly approved new run. Expired results cannot be reused as current calibration.

## Privacy and evidence limits

All contexts, expected decisions, outputs, operation records, checkpoints and artifacts
are evaluator-only. They may contain withheld tests, inspected source, evidence text
and reviewer explanations. Keep the artifact store private and disjoint from worker
exports; the runner returns a digest and sanitizes propagated failures, not a public
context/output report. The model request is the explicitly authorized protected review
boundary, never a builder prompt. Operator-supplied text still requires rights and
leakage review; hashes cannot detect semantic contamination.

This Python API does not receive repository/worker-root configuration and cannot discover
every consumer of a directory. The full controller must validate that the dedicated ledger
and protected artifact store are outside all configured worker/export roots before invoking
it. The private directory boundary is caller-owned, not asserted by this module.

Ledger receipts and artifact hashes rely on trusted writer/storage boundaries. They
do not authenticate arbitrary fabricated writers or prove a judge's semantic accuracy.
Per-call model costs use the configured rate card, not invoices, and do not measure
infrastructure or human effort. Matching a small approved development set does not
establish broad task correctness, historical benchmark validity or human benefit.
Independent judge contexts can remain correlated, especially for the same provider.
Calibration is necessary evidence for the intended gate, not a substitute for the
qualification protocol, authoritative deterministic tests or campaign preregistration.

`tests/test_calibration.py` runs the real broker and separate SQLite evaluation ledger
with controlled HTTP transports. Its source/rights/runtime/expected-answer material is
explicitly synthetic; mocked decisions are not actual agent judgments. Tests cover
both provider shapes, measured success/failure, private expected answers, policy and
held-out-split refusal, immutable resume, unknown reservations, a post-settlement crash,
changed bindings, expiry and revocation. No paid calibration call or actual historical
admission is claimed by those tests.
