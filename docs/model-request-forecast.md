# Pure model-request reservation forecast

`integrations.model.forecast_request` computes the broker's exact current reservation
metadata without obtaining an API key, constructing a transport client, accessing a ledger,
reserving budget or calling a provider. This v8 preparation work is separate from the
preceding v7 hosted validation; it does not authorize or claim a live evaluation run.

```python
from dataclasses import asdict

from agentic_delivery.integrations.model import forecast_request

forecast = forecast_request(
    configured_model,
    instructions=trusted_instructions,
    context=prepared_context,
    output_type=TrustedOutputContract,
)
metadata = asdict(forecast)
```

The result is a frozen, slotted `ModelRequestForecast` containing only provider identity,
request/prompt/context/schema/configuration SHA-256 digests, `serialized_body_bytes`,
`upper_input_tokens`, `max_output_tokens`, and `reservation_microdollars`. It contains no
prompt, context, request body, model name, environment-variable name, credentials or raw
configuration. Its scalar fields cannot be changed through ordinary attribute assignment.
Digests identify content; they are not attestations or execution permissions.

The forecast revalidates `ModelConfig` and structured input types, requires JSON-serializable
finite context, and derives the output schema from the trusted Pydantic model class. Invalid
input failures are sanitized rather than echoing submitted values. The output class is
application code, not an untrusted runtime import. Forecasting temporarily constructs the
same private request body in memory; the returned object exposes only metadata. Do not
log inputs or private request-preparation internals.

## Exact reservation semantics

`StructuredModel.generate` and the pure forecast share the same private body constructor.
Provider-specific body shapes and Unicode handling remain unchanged: OpenAI context JSON
retains Unicode, while Anthropic context JSON retains its existing escaped-ASCII encoding.
The request digest uses the broker's existing canonical JSON digest function. The schema
digest binds the original Pydantic schema; provider-specific schema transformations remain
part of the actual body and therefore its request digest.

The conservative input reservation is:

```text
serialized_body_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
upper_input_tokens = serialized_body_bytes + 1024
max_output_tokens = configured max_output_tokens
reservation_microdollars = ceil(
    (upper_input_tokens * input_microdollars_per_million
     + max_output_tokens * output_microdollars_per_million) / 1_000_000
)
```

The implementation uses integer arithmetic for rounding. The serialization basis preserves
the broker's default JSON spaces. It is deliberately **not** the compact byte length HTTPX
uses on the wire. It is a conservative reservation heuristic, not tokenizer output or a
prediction of actual provider usage. Provider-reported usage still settles through the
existing conservative ledger and receipt validation; uncertainty retains reservations.

Rates or rate-card/configuration changes alter configuration provenance even when the wire
body is unchanged. Output limits, prompt, context and schema changes can also alter the
request and reservation. Recompute a forecast from the exact frozen inputs before making
a separately authorized finite-run budget decision. A forecast neither admits a request
against current account balances nor relaxes cached-operation provenance checks.

## Validation

Controlled HTTP transports compare the exact pre-refactor wire shape/bytes and the forecast
against actual ledger reservations and settled receipt digests for both providers, including
Unicode, changed schemas, rates, output ceilings and timeouts. Exact cached retries make no
second transport request. Pure-function tests forbid credential/client access, check returned
metadata for private canaries, exercise immutability and input preservation, and reject
non-JSON, nonfinite, circular and invalid contract inputs without exposing their content.
These tests make no paid provider calls and establish no benchmark or provider billing result.
