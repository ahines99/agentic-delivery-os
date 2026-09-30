# Correlated operational events

`delivery-service run` and `delivery-service worker` enable a JSON metadata stream
through `agentic_delivery.events`. No collector service or external endpoint is
required. Other command modes retain their existing output. This implements activity
and model-operation observations from the M4 operational plan; it does not declare
the complete telemetry/measurement requirement finished.

Every event has `event: delivery.operation`, `schema_version: 1`, a UTC observation
time, kind and status. In this single-tenant workflow, one workflow is one logical
delivery attempt, so `trace_id`, `workflow_id` and `attempt_id` share its canonical
UUID. Distinct rerun workflows remain distinct attempts and can be joined through
the canonical rerun records. These fields are not an OpenTelemetry trace protocol.

| Observation | Correlation and numerical fields |
| --- | --- |
| Activity start/completion/failure/cancellation | Temporal activity operation ID, allowlisted activity name, SDK retry attempt, per-attempt queue time and elapsed milliseconds |
| Model reservation | Stored plan/build/review operation ID and reserved microdollars |
| Acknowledged model settlement | Same operation ID, recorded cost and elapsed milliseconds |
| Cached model recovery | Same operation ID; no new charge field |
| Unconfirmed model completion | Same operation ID and elapsed time; cost remains absent |

Activity `COMPLETED` means its function returned. It does **not** mean the returned
business outcome was successful or the ticket is ready. For example, an activity can
return a policy-blocked result normally. Model `SETTLED` means local settlement was
acknowledged, not that the provider invoice was reconciled or the generated change
was correct. A lost settlement acknowledgement may emit `UNKNOWN` even when the
database committed; the durable ledger remains authoritative.

Only canonical workflow UUIDs, known operation formats, named activity types, fixed
statuses and bounded nonnegative integer measurements are emitted. Unsupported
operation IDs become null; unsupported workflow IDs produce no event. Requests,
arguments, results, ticket text, prompts, code, headers, URLs, configuration,
credentials and exception messages are never serialized by this stream. Logging
errors are swallowed so a failed diagnostic sink cannot replace an application
result or trigger a duplicate provider operation.

The service enables only this named logger. It does not turn on third-party request
logging or claim to sanitize all SDK/Uvicorn output in the surrounding private log.
Do not export an entire service log as if it were this allowlisted metadata stream.
The separate [operational export](operations-export.md) remains the supported bounded
database report.

## Recorded verification

On 2026-09-30, the initial event/Temporal-CI selection passed **18 tests in 45.94
seconds** using isolated PostgreSQL and real Temporal. The later event/model-fault
selection passed **16 tests in 31.96 seconds**, including real PostgreSQL fault cases,
real worker interceptor execution and history replay. A broader model, receipt,
reconciliation and service selection passed **141 tests with seven explicit missing
service skips in 25.54 seconds**. Ruff, formatting and mypy passed. Counts overlap;
they are not additive coverage. Full-source regression and installation are pending.

Owned payload canaries remain absent from captured events on success, provider
failure, cancellation and lost settlement acknowledgement. Tests retain the original
activity result/exception, current ledger dispositions and one HTTP operation after
cached recovery. No real provider credentials, paid model call or live delivery
database was used.

## Measurement limits

The stream is best-effort and can be lost or repeated across process failure. Summing
log lines is not billing or an exact operation count. Use the durable workflow,
command and usage records for authoritative counts and uncertainty. Queue and active
durations describe the observed SDK activity attempt; they do not measure the whole
ticket's wall time or human review latency.

The complete plan still calls for consolidated lifecycle timing, correction,
clarification, cancellation, cleanup, duplicate and provider-error metrics. False-ready
rates and human review benefit require independent outcome observations and remain
unmeasured. Nothing here replaces historical evaluation or human pilot signoff.
