# Executed development calibration

`evaluation/calibration.py` implements a bounded calibration runner and evidence
validator. It exercises the same protected `ReviewContextV2`, `ReviewOutputV2` and
`qualifier_prompt(rubric_text)` used for qualification review. It does not admit a
historical task, run the benchmark campaign, authorize a merge or override deterministic
tests. Current [campaign preparation](evaluation-campaign.md) consumes this evidence through
the concrete qualification authority. Legacy metadata remains unverified inspection material.

The runner consumes already prepared protected contexts; it does not import or independently
attest their provenance. [Owned synthetic preparation](synthetic-preparation.md), protected import,
[ledger-verified runtime/context assembly](qualification-inputs.md) and explicit
[negative/uncertain review subjects](calibration-subjects.md) provide the development bootstrap.
Controlled test fixtures are not a substitute for actual preparation and paid model receipts.

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


## Recorded live development calibration

On 2026-09-28, five original development contexts backed by 65 actual Docker operations
were reviewed through the configured live Anthropic broker. The original frozen expected
findings were unchanged. All five provider calls settled; recorded usage was 45,235 input and
20,370 output tokens, costing **735,425 microdollars ($0.735425)** under the bound rate card.
The exact five-call reservation ceiling was $1.183110, within a separate $5 stage cap.

The result was **CALIBRATION_FAILED**: five of five verdicts and all expected finding statuses
matched, but only one of five responses met the complete evidence contract. One response
added an unexpected finding target; three omitted required eligibility citations. The valid
case was the unresolved case. False admits were zero; the safety and false-admit mandatory
cases failed their complete contract checks, giving two mandatory failures. These five toy
cases do not estimate general benchmark accuracy.

Cached resume reproduced the same evidence and accounting without another provider call.
All five operations are settled, with zero remaining reservation. The failed result cannot
authorize subsequent qualification; no fresh full qualification or historical campaign ran.
Original provider records and diagnostic metadata remain private. The earlier unrelated
provider probe remains unresolved and was not retried.

An offline initialization failure preceded these calls: edge whitespace in the raw rubric
conflicted with the normalized review contract. The shared prompt normalization fix preserved
raw artifact identity and expectations. A prompt-only derivative specification and recovery
of the original unused identity/deadline are documented in the
[preparation record](synthetic-preparation-runtime.md#recorded-execution). Future prompt
revisions require new frozen specifications and separately metered calibration; this failed
run remains part of the development record.


## Revised prompt: passing development calibration

The `b9b8391` prompt revision makes the existing finding IDs and citation requirements explicit;
validators, schema and expected decisions are unchanged. On 2026-09-28 a new finite five-call
stage used the same frozen development cases and actual Docker evidence. All five responses
were valid and matched every expected finding and verdict: **CALIBRATED**, zero false admits
and zero mandatory failures. Recorded usage was 48,566 input and 20,706 output tokens, costing
**760,480 microdollars ($0.760480)**, below the exact $1.235935 reservation ceiling and $5 cap.
Cached resume returned the same evidence and accounting without another provider call.

The previous failed stage remains retained. Combined model cost for these two calibration
stages is **$1.495905** across ten calls. Reusing development cases to correct output-contract
instructions does not measure held-out judge accuracy or historical benchmark performance.
This pass authorizes only subsequent work allowed by the current calibration policy and the
separate qualification/spending gates; it does not admit a historical task.

## Subsequent qualification stopped at a truncated review

A fresh synthetic qualification completed its preflight and twelve repeated Docker
checks (13 settled infrastructure operations; 26 microdollars of local estimates).
Its first independent model review returned HTTP 200 with `max_tokens`: 8,683 input
and 5,000 output tokens were reported, but no complete review was accepted. The
operation retained its **234,400-microdollar reservation**, with actual ledger cost
unsettled. The second reviewer and adjudicator did not run. No qualification record,
admission, worker export, scoring or campaign authority resulted.

The private driver stopped without retrying or aliasing the operation. Reported
usage alone is not a successful review receipt; explicit failed-call reconciliation
is separate work. This does not alter the preceding five-case calibration result.
Its current-use grant must still be valid for any later qualification attempt.

The later [failed-call reconciliation](model-failure-reconciliation.md) matched the
original sealed request, immutable provider observation, configuration and reservation.
It settled **168,415 microdollars ($0.168415)** of configured-rate model usage and
released the remaining reservation. Combined with infrastructure, that failed attempt
cost 168,441 microdollars. The receipt explicitly records failure and grants no retry.
Reapplying reconciliation returned the same receipt without calls or accounting changes.
The truncated review remains unusable for qualification. The earlier unrelated probe
still has an unresolved reservation and was not touched.

## Calibration with a larger output allowance

After the failed review's accounting was closed, a separate stage retained the
same five development cases, expected findings, rubric and prompt. Only the model
configuration changed to an 8,000-token output limit and a 180-second timeout. Its
new specification and grant permit twelve hours of current use within the original
data authorization, with a 30-minute execution deadline and five fixed operations.

All five responses again satisfied the evidence contract and matched the frozen
expectations: **CALIBRATED**, zero false admits and zero mandatory failures. Recorded
usage was 48,577 input and 19,386 output tokens, costing **727,535 microdollars
($0.727535)** under the exact $1.610935 reservation ceiling and $5 hard cap. Cached
resume reproduced the same result without another call or charge. The two earlier
calibrations remain retained; combined configured calibration cost is **$2.223440**
across fifteen calls. This remains reused development evidence, with no historical
admission or held-out accuracy claim.

## Completed synthetic qualification

The newly calibrated configuration then completed a fresh owned-fixture qualification:
preflight and twelve repeated baseline/reference Docker checks, followed by two
independent, fully validated model reviews. Their findings agreed, so the conditional
adjudicator did not run. Status is **SYNTHETIC_VALIDATION_PASS**; reconstruction of the
complete record passed the authority's synthetic-validation checks.

The two model calls used 17,441 input and 11,067 output tokens and cost **363,880
microdollars ($0.363880)**. Thirteen Docker operations added 26 microdollars of local
infrastructure estimates, for 363,906 microdollars total. All operations settled with
zero remaining reservation. Cached recovery reproduced the same qualification artifact
and accounting without further Docker or provider effects. No managed containers remained.

Synthetic classification was explicitly checked against every consumer: historical
admission, worker export, scoring and campaign use remained denied. This is an executed
development validation of the complete machinery, not an admitted historical task or a
benchmark score. The earlier truncated qualification remains a separate failed record.

## Historical review capacity calibration

After the first PR 404 historical review hit the 8,000-token output limit and its
financial accounting was closed, a new five-call stage changed only the model's
output limit to 20,000 tokens and timeout to 300 seconds. The original fixture
artifacts, expected findings, decisions, rubric, prompt and schema were unchanged.
The controller froze exact forecasts, a $20 cap and a 30-minute execution deadline.

All five outputs were valid and matched the frozen expectations: **CALIBRATED**,
zero false admits and zero mandatory failures. Usage was 48,575 input and 20,867
output tokens, costing **764,550 microdollars ($0.764550)**, below the exact
$3.110960 reservation ceiling. All five operations settled with zero reservation.
Across the four retained calibration stages, configured model cost is **$2.987990**
for twenty calls. These reused development cases do not measure held-out accuracy.
The new calibration does not itself admit the historical candidate or erase its
[earlier failed review](historical-development-attempts.md#pr-404-outcomes).
