# Model-operation receipts

The structured model broker now records a validated receipt for each successfully
settled call. The delivery ledger and separate evaluation ledger implement the same
reservation/settlement/read protocol; an evaluation account does not authorize a paid
call, a campaign, task admission, or delivery work.

## Recorded provenance

A receipt binds the account and logical operation ID to the provider, the response
body's `id` as `provider_response_id`, requested model and returned model. The legacy
settled-result alias `provider_id` retains the same response/message object identity.
Neither field captures an HTTP request-correlation header; that separate identifier
remains unmeasured. It records UTC-aware request-start and
completion timestamps, actual input/output token counts from that response, calculated
cost and the configured versioned input/output rates. Completion cannot precede start;
token counts and costs must be nonnegative integers, never coerced booleans or strings.

SHA-256 digests bind the canonical constructed JSON request payload (not HTTP wire bytes), instructions, context, output
schema, model configuration and validated structured output. The receipt contains
digests rather than raw instructions/context or credentials. The configuration digest
includes the secret environment-variable name, not its secret value. These hashes
identify bytes; they are not encryption, provider signatures or authentication of an
arbitrary writer. Guessable low-entropy inputs can still be recognizable by their hash.

The surrounding private ledger result retains the structured output, provider metadata
and receipt. `operation_receipt(account_id, operation_id)` is an internal trusted
controller read, not a new public API or automatic permission to export the result.
It denies a different account and returns reserved/actual accounting plus a digest of
the returned operation document. Treat the complete document as private evidence;
unlike the receipt alone, it includes model output.

Costs are the ceiling of token counts multiplied by the configured per-million-token
rates, expressed in integer microdollars. They are **not a provider invoice** and do
not independently establish cached-token discounts, special service tiers, taxes,
infrastructure cost or human effort. Requested and returned model identities are both
retained; their presence does not verify that the configured rates match the provider's
billing for that returned model. Actual token counts are per operation, not copied from
account totals or token reservations.

## Retry and uncertainty rules

The broker reserves conservative token/cost limits before network I/O. A settled retry
revalidates its account-scoped ledger record, accounting/ceilings, result identity,
receipt and all current request bindings before returning the original structured
output. It makes no new provider call and invents no new timestamps. Reusing the same
operation ID with changed instructions, context, schema or model configuration is
denied before network I/O. Accounting/provenance/output tampering also denies the retry.

Before validating structured output or settling a received response, the broker records one immutable
`ProviderObservation`: account/operation/provider, request/configuration digests, timestamps,
HTTP status and a SHA-256 digest of the raw response bytes. Allowlisted optional fields
retain a valid body response ID, model, known termination label and individually valid
reported token counts. Unknown termination text becomes `OTHER`; absent or malformed
counts remain null, never zero. Raw response bodies, headers and error strings are not
retained. Transport errors and cancellation record their outcome without inventing HTTP
status, response metadata or token counts. A cancellation observation describes interrupted
local waiting; it does not prove that a remote provider stopped work or incurred no charge.

An observation is diagnostic evidence, not a parsed answer or settlement authority. The
ledger rejects replacement with different observation bytes, allows an identical repeat,
and preserves it through settlement. Recording one never releases cost/token reservations.
The settled receipt validator cross-checks any recorded observation and its top-level
alias against the receipt's provider/request/configuration, model/response ID, usage,
timestamps, success status and termination before cached output can be returned.

Missing or malformed response-identity/model metadata, incomplete output, malformed usage, failed
response validation or an uncertain network outcome cannot fabricate a settled receipt. Their
reservation remains unresolved (`RESERVED`, operationally UNKNOWN); it cannot be silently
retried with a fresh operation identity to avoid the budget. Provider parsing failures
use sanitized exceptions without chained private validation data, including when
converted to Temporal failure payloads. Reconciliation remains an explicit operational
responsibility; a reservation is neither a zero-cost result nor proof of billed usage.
Observed token counts, when present on a rejected response, remain explicitly reported
metadata; they do not silently become settled actual cost or release the reservation.

Legacy settled operations without these receipts remain legacy. Their previously
recorded actual cost can be read, but per-call actual token counts are unknown when
they were not retained. The new broker refuses to upgrade them by guessing from
aggregate account totals, inventing timestamps or reissuing the provider call. The
delivery schema stores new per-call token provenance in the committed result; its
retrieval check is not an independent source of token truth. The dedicated evaluation
ledger additionally stores its actual per-operation counters.

The validator checks internal consistency against trusted ledger data. Someone able to
rewrite the result, hashes and accounting coherently could fabricate a new consistent
record; these receipts do not provide cryptographic attestation or semantic correctness.
Operator-owned database/artifact access and independent evaluation qualification remain
separate controls. Hashes do not convert a fixture into an executed agent decision.

## Bounded evidence

`tests/test_model_receipts.py` uses HTTP MockTransport responses and isolated SQLite
ledgers only. It exercises both provider wire shapes, canonical request/output digests,
per-call usage versus account totals, timestamps, ceiling-rate arithmetic, immutable
cached retries, request changes, cross-account reads, legacy records, malformed
metadata/envelopes, accounting/provenance/output tampering and private-error suppression
through the actual Temporal failure converter. Both delivery and dedicated evaluation
ledgers complete the same broker settlement/cache contract. Additional regressions preserve
HTTP rejection/termination/malformed-body observations, raw-response digests, null malformed
usage, transport/cancellation outcomes and immutable observations without releasing budgets;
changed nested observations or top-level aliases fail cached validation.

Independent review identified and corrected cached-output reuse that had omitted
ledger accounting validation and malformed-envelope handling that could escape the
sanitized exception path. These are negative-control regressions, not real provider
calls or paid usage evidence. No historical task has been admitted, no benchmark
campaign executed and no model bill reconciled by this test suite.

## Actual unsuccessful probe, separate from fixtures

On 2026-09-28, an authorized synthetic Anthropic nonce/status probe used account
`synthetic-model-provenance-24346e68a8b9410e9431b21e36c750ef` with a 100000-microdollar
cap. It ended in `ModelFailure`, leaving **14465 microdollars RESERVED**, no output
receipt, and no retry. Recorded settled cost zero does **not** mean the provider's
actual final cost is zero or known. The existing private
`delivery_eval_model_provenance.sqlite` remains outside the repository under the user's
artifacts directory for reconciliation.

The failed probe preceded the observation feature. Its HTTP status, termination reason
and provider response ID were not retained; its actual cause is unknown. They cannot
be inferred or reconstructed from the reservation, exception class or later mocked tests.
The gap led to the diagnostic observation change described above, which applies to future
calls only. No further paid call or successful live receipt is claimed here.
