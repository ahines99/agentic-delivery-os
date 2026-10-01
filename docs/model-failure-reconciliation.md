# Failed model-call financial reconciliation

`integrations.model_reconciliation.reconcile_max_tokens_failure` closes the financial
reservation for one narrowly supported failure in an **EvaluationExecutionStore**.
It does not accept the delivery Store, make a network request, read a credential,
create a reservation, grant another attempt, or turn a failed response into an answer.
This is a trusted local accounting operation; the caller must already be authorized
to inspect the original protected request and settle the specified evaluation account.
It is not an API endpoint or general authorization mechanism.

The caller supplies the account/operation IDs, original `ModelConfig`, instructions,
context and output-schema class, and an independently selected
`expected_observation_digest`. The function recomputes `forecast_request` itself.
Its optional aware `now` parameter supports controlled tests; production controllers
should use the real clock. There is no requirement to renew the original execution
grant merely to account for an already attempted call.

All of the following must hold before settlement:

- The immutable ledger observation is a complete, canonical `ProviderObservation`
  matching its stored alias, expected digest, account, operation, request, and config.
- The provider is Anthropic, HTTP status is exactly 200, and termination is exactly
  `max_tokens`. A response ID and response digest must exist. The returned model must
  equal the configured model exactly; model aliases are unsupported.
- Positive integer input/output usage is present. Output usage equals the configured
  maximum, input usage fits the original forecast, and all three reserved quantities
  exactly equal the original pure forecast. Counts and amounts fit signed 64-bit storage.
- Reservation creation precedes request start; start precedes observation; observation
  is not in the future. An existing settlement must follow the observation and must not
  be in the future.
- The operation is observation-only `RESERVED`, or is already the exact same financial
  failure settlement. Missing metadata, transport failures, cancellation, other stop
  reasons, altered rates, overflow, and successful results are refused.

Cost uses the configured rate card and the same ceiling calculation as the broker:
`ceil((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000)`.
This is configured-rate accounting from captured provider usage, **not an invoice**
or independently verified provider bill. Digests bind bytes; they do not authenticate
an arbitrary ledger writer or independently attest to a provider response.

The frozen `FinancialFailureReceipt` is stored under `financial_failure_receipt`,
alongside the unchanged `provider_observation`. It explicitly records failed execution
and no retry authorization. No `output`, `operation_receipt`, or successful-provider
result aliases are added. Existing successful receipt consumers reject this result;
the broker's cached path rejects it before issuing another HTTP request.

The receipt uses the original observation timestamps, so identical concurrent callers
produce the same document. The ledger's immutable `settled_at` records when financial
settlement occurred. Atomic ledger settlement prevents double charging and rejects
incompatible concurrent results. Unknown reservations stay reserved on validation
failure. If a different trusted actor wins a settlement race, its result is preserved
and reconciliation fails rather than replacing it. The account can then have known
spend while its execution stage remains failed; this does not authorize account
replacement, workflow continuation, calibration admission, or retry.

Focused tests use synthetic observations, an HTTP mock returning a truncated response,
SQLite reopening, and optional real PostgreSQL concurrent callers in a uniquely named
disposable evaluation database. They do not modify private run ledgers or call a paid
provider. A future delivery-ledger adapter needs separate receipt/accounting integration
and review; it is intentionally outside this implementation.

## Recorded development recovery

On 2026-09-28, this path reconciled the first truncated synthetic qualification
review described in the [calibration record](evaluation-calibration.md#subsequent-qualification-stopped-at-a-truncated-review).
The private controller reconstructed the original sealed request and checked its
observation, configuration, plan and reservation before settlement. Reported usage
of 8,683 input and 5,000 output tokens produced 168,415 microdollars of configured
model cost; the 234,400-microdollar reservation became zero. Thirteen completed Docker
operations added 26 microdollars of local infrastructure estimates.

Reconciliation and its cached reapplication made zero provider calls and produced
the same failure receipt. The second review and adjudication never ran. The failed
review supplies no qualification or retry authority. A separate earlier probe has
insufficient known outcome metadata and retains its original reservation.
