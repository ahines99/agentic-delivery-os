# Complete private qualification controller

`evaluation.qualification_controller.run_qualification` connects preparation, executed
calibration, the deterministic Docker matrix and independent protected model reviews. It
returns the digest of a private `QualificationRecordV2`. Consumers must validate that record
using the current [admission authority](qualification-admission.md); returning a digest does
not itself authorize export, scoring, campaign admission or additional spending.

The trusted caller supplies the frozen `QualificationRequestV2`, current authorization,
settings and preparation/calibration policy providers, protected and output artifact stores,
a disjoint worker directory, a separate evaluation ledger and the configured model broker.
The broker must use that exact ledger and model configuration. There is no offline CLI
shortcut for constructing a trusted authority from arbitrary task JSON.

## Execution and restart

1. Validate preparation, current data permission and executed calibration before effects.
   Freeze the request, authorization, execution deadline and three distinct planned review
   invocations in `qualification-plan-v2`. The third invocation is conditional adjudication.
2. Run the metered isolation preflight and twelve deterministic checks. Verify the complete
   ledger and collector chain before copying its exact artifacts into the protected store.
   Freeze the qualification input using those verified receipts.
3. Assemble two independent review contexts from the same bounded source, issue, oracle and
   normalized outcomes. Neither initial context contains its peer's output. Neither receives
   the reference solution or raw runner output. Each actual model operation reserves budget
   and binds its prompt, schema, configuration, context, output and provider usage receipt.
4. Seal each validated review. If any target finding differs, invoke the planned adjudicator
   with both sealed outputs. A negative or unresolved review result remains private evidence;
   admission still fails. Agreement does not establish semantic correctness.
5. Freeze the derived result and exact account snapshot, recheck current authority and write
   `qualification-result-v2`. The admission reader independently reconstructs the full chain.

The thirteen infrastructure operations and two or three model operations share the same
qualification account and total cap. Calibration retains its own accounted execution; scoring
requires a [separate grant and account](scoring-execution.md). Infrastructure amounts are
rate-card estimates, not external invoices. There is no campaign-wide account hierarchy yet.

Exact settled operations and immutable checkpoints support resume without repeated Docker or
model calls. A lost review checkpoint can be reconstructed from a settled broker receipt.
An unknown operation retains its reservation and cannot be reissued. Changing a grant or
account binding does not renew its original deadline. Controller resume requires the original
execution window; later consumption uses authentic completion timestamps plus current use
permission, as described in the admission document.

Current authority and path separation are checked at effect boundaries and polled while the
runtime and model calls are active. Parent model-permission revocation also cancels an active
deterministic stage. Cancellation retains ownership of cleanup even under repeated cancellation.
Host/process failure can still leave uncertain work; no automatic reconciliation is claimed.

## Evidence boundary

Focused tests exercise independent contexts, conditional adjudication, cached recovery,
revocation, cancellation and retained unknown reservations. An actual Docker integration runs
the complete qualification matrix, validates admission, exports source without protected
answers, scores a candidate under a separate metered grant, and resumes without extra spend.
Its model responses and task records are controlled synthetic fixtures. It proves those
software paths, not live judge calibration or qualification of any historical catalog task.

Requests classified `SYNTHETIC_VALIDATION` can produce diagnostic records, never worker export,
scoring or historical campaign admission. Contract tests that exercise the historical branch
with synthetic records are not imported into the historical catalog or published as benchmark
results. A real authorized calibration and historical qualification run remain required.

The classification does not yet provide a local synthetic provenance importer. Preparation
still requires the pinned GitHub issue, license and accepted-commit fields of the historical
contract. Project-owned local toys must not invent that history to satisfy the schema. An
explicit synthetic provenance path and a ledger-verified runtime-to-calibration-context producer
are the next prerequisites for an honest live synthetic run. Negative calibration subjects also
need a truthful representation separate from the harmless code permitted to execute.
