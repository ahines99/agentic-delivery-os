# Protected qualification review stage v2

`evaluation/qualification_v2.py` provides strict review contracts, protected context assembly,
structured finding validation and current model-ledger receipt checks. It makes no model calls,
writes no artifacts, and never admits a historical task. A successful combined result is
`status=PASS, admitted=false`: only the review stage has passed.

## Actual evidence and visibility

`assemble_review_context(artifacts, qualification_input_artifact, *, rubric_artifact, stage,
context_id, peers=())` reads the existing immutable `QualificationInput` and its artifacts.
It verifies the complete twelve baseline/reference acceptance/regression receipt matrix using
the established deterministic execution checker, rejecting incomplete collection/phases,
unexpected outcomes and reused execution identities. Existing v1 semantic review/admission is
not invoked.

The resulting `ReviewContextV2` has explicit `EVALUATOR_ONLY` visibility and contains:

- Actual pre-fix source and oracle file mappings, their artifact identities, the frozen WorkItem,
  provenance, family/split and declared controller checks.
- Actual bounded supporting document text for license, authorization and the six eligibility
  dimensions; the frozen rubric; observed acceptance/regression node identities.
- Normalized per-repetition outcomes derived from the validated receipts. Raw stdout, stderr,
  exception tracebacks and reference source/patch contents are excluded.

Initial qualifier A and B receive the same `evidence_digest` with distinct context IDs and no
peer outputs. They can inspect the actual tests when assessing undocumented requirements,
overfitting and missing coverage. The accepted reference remains a deterministic existence
proof, excluded from initial and adjudicator model contexts.

This changes no builder export. The caller must already hold active authority to read and send
these protected artifacts to the configured provider. Never place the context, findings or raw
receipt payloads in worker inputs, public exports, general logs or interactive agent transcripts.
Evaluator-only qualification access is not permission to reveal sealed-test failures to an arm,
tune prompts against them, or restart a release comparison.

Assembly excludes exact reference artifact identities from supporting-document/rubric roles.
It cannot prove that arbitrary imported free text contains no paraphrased solution, peer
judgment or secret. The trusted importer must enforce those boundaries. Imported rights and
family assertions remain inspectable claims, not independent legal clearance or complete
cross-corpus proof. Full source/oracle context is bounded at 512 KiB including peers, with each
supporting document/rubric limited to 32 KiB and existing snapshot bounds enforced. Oversized
material is rejected; nothing is silently truncated.

## Output, citations and adjudication

`ReviewOutputV2` has explicit `schema_version=2`, a verdict, findings, limitations and
`resolved_disagreements`. It requires exactly one finding for each eligibility dimension
(`rights`, `risk`, `runtime`, `leakage`, `family`, `oracle`) and every WorkItem criterion.
Each finding has a concise reason, status and citations. No private chain of thought is requested.

`validate_review_output(output, context)` checks that cited artifacts were supplied, file line
ranges exist, and cited nodes were observed in the named file or execution. Criterion findings
must cite inspected oracle lines and an observed acceptance node. Rights findings cite both
license/authorization records; risk/leakage cite source; runtime cites an execution; family cites
its supporting record; oracle findings cite actual oracle content. These checks establish
coverage and traceability, not whether the model's interpretation is correct.

A `FAIL` finding requires `REJECT`; otherwise any `UNRESOLVED` requires `UNRESOLVED`; only all
`PASS` permits the model verdict `ADMIT`. That model verdict grants no authority. Initial
reviews have no resolved-disagreement entries. A third context receives both sealed structured
outputs, including their reasons and citations, and the identical frozen evidence. It must
address exactly the target keys with differing statuses (for example `criterion:AC-1`). Missing
adjudication, invented resolutions, peer replacement, reused context/provider-operation
identities or unnecessary adjudication are rejected. An unresolved adjudicator verdict remains
unresolved. Review judgments cannot override failed or pending deterministic eligibility.

## Exact broker and storage bindings

`qualifier_prompt(rubric_text)` constructs the same rubric-bound prompt for review and calibration.
The future executor stores complete normalized `context.model_dump(mode="json")` and
`output.model_dump(mode="json")` documents in protected artifacts. `ReviewRecordV2` binds their
artifact identities to the account and operation ID.

`validate_review_record(..., ledger, account_id, config, expected_task_manifest_digest,
expected_input_artifact, rubric_artifact, peers=())` retrieves the current settlement from the
trusted ledger through `operation_receipt`, calls `validate_operation_receipt`, rebuilds the
context from immutable evidence and checks exact task/account, prompt, output-schema,
configuration, context and output bindings. Provider/model and rate-card fields must match the
expected configuration. Missing/unknown settlements and legacy receipts without required
provenance cannot pass. All errors from protected parsing/validation are reduced to generic
messages without chaining source-bearing exceptions.

`validate_review_context(context, artifacts, peers=())` performs evidence reconstruction without
a model receipt and is useful before calibration/model effects. Calling only the output
validator does not independently authenticate a supplied context. `ValidatedReviewV2` is a
protected in-process validation result, not a signed capability or a deserializable source of
authority. `resolve_reviews(first, second, adjudicator=None)` accepts records just validated
against the trusted ledger and produces metadata only. The caller must not substitute arbitrary
client-created `ValidatedReviewV2` values. Hashes bind records but do not authenticate their writer.

## Integration boundary and compatibility

This standalone module does not change `HistoricalTask`, v1 qualification records, preparation,
CLI admission or campaign freezing. V1 outputs cannot be parsed as v2 by adding default fields.
The complete future controller must require current preparation authorization, actual runtime
receipts bound to the execution ledger, executed calibration for these exact prompt/schema/model
settings, active policy, cost accounting, fresh protected reviews and an explicit versioned
admission record. These review contracts alone cannot mark v1 tasks newly qualified.

The tests use explicitly synthetic task/rights/runtime records and synthetic model settlements
written to a real SQLite ledger. They test evidence/citation binding, reference/log exclusion,
independent contexts, adjudication, unknown reservation handling and absence of admission.
No historical answers or provider calls are needed. Actual semantic qualification and calibrated
model performance remain separate evidence requirements.
