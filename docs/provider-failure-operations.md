# Model provider failure operations

Provider failures stop the affected authorized operation. They do not authorize a
new account, a retry alias, a larger budget, a different model or a new deadline.
Continue independent implementation and controlled tests while retaining the failed
operation and its conservative reservation.

The broker persists an allowlisted `ProviderObservation`: request/configuration
digests, timing, HTTP status and response digest, plus supported response identity,
termination and reported usage fields when present. It excludes raw response text.
An observation is neither a parsed successful answer nor financial settlement.
Missing usage is unknown, not zero. Inspect only scoped accounting and observation
metadata; do not dump the operation's model output or private request context.

HTTP failure exceptions now include a fixed diagnostic category, such as
`authentication`, `permission`, `rate_limit` or `provider_unavailable`. For Anthropic,
a recognized spend-limit code or bounded credit/spend-limit message produces
`billing_or_quota_hint`; the upstream text is never copied into the exception.
This follows the provider's [error categories](https://platform.claude.com/docs/en/api/errors)
and [spend-limit distinctions](https://platform.claude.com/docs/en/api/rate-limits#spend-limits).
Malformed or unsupported details retain the generic HTTP category. The hint is
operational guidance only: observation schemas/digests, reservations and retry rules
are unchanged. It cannot reconstruct causes for older observations or settle a charge.

## Classify before further effects

1. Identify the original account, immutable plan, operation and grant. Preserve the
   original timestamps and remaining reservation. Determine whether a complete
   settled receipt, HTTP observation, transport failure or cancellation exists.
2. Validate settled operations through their normal read-only consumer. A missing
   operation with a retained stage/result checkpoint is inconsistent evidence and
   must not be recreated. Partial recovery never extends the original deadline.
3. Interpret HTTP metadata conservatively. For example, Anthropic documents HTTP
   400 for request problems and configured organization/workspace spending limits.
   Status alone cannot determine the cause. Its
   [error reference](https://platform.claude.com/docs/en/api/errors) describes error
   categories and correlation IDs; arbitrary upstream message text can echo inputs
   and must not enter public logs or implementation-agent context.
4. If a separate capability diagnostic is justified, give it its own original
   non-sensitive input, immutable plan, exact forecast, finite one-call budget and
   deadline. Retain its outcome and uncertainty separately. Such a diagnostic does
   not retry, settle or establish the cause of the earlier operation.
5. Restore the actual missing prerequisite before authorizing further live work.
   A provider capacity change does not itself authorize retry, replace the retained
   outcome or make an old grant current. Do not change billing limits or payment
   settings as an inferred recovery action.

## Financial reconciliation

The implemented [failed-call reconciliation](model-failure-reconciliation.md) handles
one narrow case: an exactly bound Anthropic HTTP 200 `max_tokens` response with
complete, internally consistent usage and the original request/configuration. It
records financial failure only; it creates neither valid model output nor retry
permission. It cannot settle HTTP 400, missing usage or an ambiguous transport result.
Those reservations remain until an applicable evidence-backed reconciliation path
exists. Do not edit ledger rows to make the account appear closed.

## Recorded development boundary

The first [final-scorer calibration attempt](semantic-calibration.md#first-live-development-attempt)
retained two paid successful broker operations and one HTTP 400 reservation. A
separate one-call diagnostic returned an invalid-request category and a billing hint.
The diagnostic retained only fixed metadata and stored its plan before credential
access. No retry or calibrated result followed that failed diagnostic. The current broker's original
observation cannot retrospectively recover an error body that was not retained.

An eventual production diagnostic extension should preserve legacy observation
bytes and digests, version additional fields explicitly, accept only fixed error
categories and bounded correlation identifiers, and fail safely on malformed error
objects. Error parsing must never suppress the existing observation or grant
settlement, retry or execution authority. That extension is not implemented by
the separate development diagnostic.

After the user restored provider billing, a new one-call diagnostic succeeded and
settled 1,670 microdollars with zero reservation. A separately authorized five-case
calibration then completed but failed its output-validation gate, as recorded in
[the calibration history](semantic-calibration.md#subsequent-completed-development-calibration).
Restored provider capacity did not settle, release or overwrite either old reservation.
