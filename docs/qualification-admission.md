# Current v2 qualification admission

`evaluation/qualification_admission.py` joins executed preparation, runtime, calibration and
independent review evidence through a concrete, trusted `QualificationAuthority`. An artifact
claiming success, an old v1 review record, or a serialized validation result is not admission.

## Contracts shared with the controller

`QualificationRequestV2` fixes the purpose classification (`HISTORICAL_QUALIFICATION` or
`SYNTHETIC_VALIDATION`), deterministic request, rubric, executed calibration specification/result,
model configuration and six controller-imported eligibility findings/evidence references.
Those mechanical eligibility findings must pass; they do not replace the subsequent semantic
reviews. The model configuration must exactly match current operator settings and calibration.

`QualificationAuthorizationV2` binds the entire request digest, original runtime authorization,
calibration-policy digest and explicit permission for model processing. Its actual bytes are
preserved as a protected artifact. The runtime grant carries one account, model/token budget,
infrastructure rate card/ceiling, shared total ceiling, issuance and expiry.

`ControllerPlanV2` persists request/grant artifact references, account, creation/deadline and
three ordered review invocations. The first two context IDs must match the pending task's reserved
reviewer IDs; the adjudicator uses a distinct context. All operation IDs are unique and scoped to
the account. `QualificationRecordV2` references that plan, runtime evidence, frozen qualification
input, two review records, optional adjudication, derived review-stage result and exact account
snapshot. Persisted records are inputs to validation, never capabilities.

The controller's model reviews and thirteen infrastructure operations (preflight plus twelve
checks) share the same account and total ceiling. Executed calibration retains its separately
validated account and recorded cost. Campaign preparation accounting must include each calibration
account once; this module does not invent a combined bill or implement a campaign-wide ledger.

## Two clocks, two distinct permissions

`validate_execution_inputs(request, grant, *, settings, preparation_policy, calibration_policy,
protected_artifacts, output_artifacts, worker_root, ledger, now)` is the pre-effect gate. It
requires the original execution grant to remain inside its wall/expiry deadline, current
preparation/data authorization and executed calibration. It returns protected validated inputs
without executing or writing anything.

Durable admission instead verifies *when execution actually completed* using the trusted
`deterministic-complete-v1` checkpoint timestamp and original grant. The historical runtime
validator checks the actual operations, receipts and ordering inside that original window.
No consumer can choose an arbitrary past clock to make stale evidence pass. At the real current
time, preparation/data rights, settings, policy and calibration must still be valid.

A separate current `CurrentUseGrant` comes from a trusted in-process provider. It allowlists exact
qualification request digests and action purposes: `qualification`, `worker-export`, `scoring`
and `campaign`, with issuance and expiry. These are actions, distinct from the request's
historical/synthetic classification. The current grant cannot be supplied by an artifact or
model judgment. Expiration of an old execution window alone does not erase authentic completed
evidence; expiration or revocation of current use/data/calibration authority blocks consumption.

## Authoritative read path

Construct `QualificationAuthority` with the protected and output stores, separate evaluation
ledger, worker root, current settings/preparation/calibration/use-grant providers and trusted clock.
Call `authority.validate(task, purpose="worker-export")` immediately before the authorized use.
The validator:

1. Reconstructs the exact v2 pending draft and checks the final task digest, permitting only the
   later attachment of `qualification_artifact`.
2. Checks current data/configuration/policy and calibration, the persisted request/grant/plan,
   and trusted `qualification-plan-v2` / `qualification-result-v2` checkpoints and timestamps.
3. Validates completed deterministic execution against the original authority and current
   preparation. The frozen input must exactly match the task, request and actual twelve receipts.
   The plan checkpoint must precede runtime binding; runtime completion must precede the input
   checkpoint, which must precede each review operation. All remain inside the original deadline.
   Copies in the protected review store must equal the verified runtime-output bytes.
4. Requires `qualification-input-v2` and each `qualification-review-<stage>` checkpoint; validates
   the actual settled model operations, contexts, prompt/schema/configuration/cost bindings and
   complete findings. Adjudication must start after both initial review checkpoints were sealed.
5. Recomputes the passing review-stage result. It checks the closed account has exactly the
   expected infrastructure/review operations, all settled inside the execution window, no unknown
   reservations or unrelated operations, exact original caps, and matching totals/account snapshot.
6. Rechecks live use permission, preparation and calibration before returning a current result.

There is no new execution or mutation in that read path. Missing, stale, unresolved, negative,
out-of-window or inconsistent evidence fails with a sanitized error. Adding a later operation to
the qualification account invalidates its closed accounting, even if the operation costs zero;
subsequent scoring/build attempts need their own authorized accounts.

`ValidatedQualificationV2.qualification_input` is protected evaluator data for the scorer;
it is not a public or builder export. Its `purpose` is the request classification and
`use_purpose` is the checked action. Historical admission requires the complete passing chain.
Synthetic classification can produce an explicitly non-admitting diagnostic result for
`qualification`; worker export, scoring and campaign actions are refused. A synthetic fixture
cannot be promoted by changing a purpose argument.

`validate_calibration_reference(task, *, artifact_digest, rubric_artifact)` revalidates campaign
use permission and checks that the supplied calibration/rubric exactly match the admitted task,
then revalidates the measured calibration against current ledger/policy. Qualifier calibration
does not establish postcandidate scoring calibration, and qualifier model identity need not
equal the campaign builder model.

## Trust and test limits

The authority, its providers, controller, ledger and artifact writer remain trusted. The code
does not authenticate an arbitrary Python caller, independently establish legal rights, prove
historical issue/commit claims, attest hostile Python, or prove semantic correctness from model
agreement. Import attestations and the protected data boundary remain necessary. No current-use
grant or budget object alone authorizes additional spending.

The tests use the complete controller, executed controlled HTTP transports, actual SQLite
ledgers and controlled collector transport with explicitly synthetic records. They exercise
current authority, closed accounting, immutable evidence, two-time validation, synthetic refusal
and export boundaries. Such a fixture exercising the historical branch does not qualify a real
historical ticket. Actual Docker and provider evidence are separately identified by the controller
integration tests and later authorized runs.
