# ADR-005: Small provider adapters, not a general agent framework

Status: Accepted for implementation. Date: 2026-09-27.

## Decision

Use one internal protocol per boundary: issue intake/status, source snapshots/publication,
model generation, execution job, and artifact storage. Keep credentials and provider response
types in adapters. Domain code receives validated immutable data, provider identifiers and
classified errors. Implement Linear, GitHub, one selected model backend and the offline Linux
runner first. A missing adapter raises an explicit unsupported-capability error.

Temporal coordinates activities and human commands. The model runner enforces structured
responses, bounded tool turns, deadlines, usage and cancellation. Tool schemas expose only
capabilities for that role/run. Models cannot register more tools or invoke credentialed
provider clients. Do not add a second agent-orchestration framework without a demonstrated
need. The [product research](../research/01-product-review.md) supports starting with simple
compositions and evaluating realistic tools.

Select the first model on the development task split in M1, recording provider/model version,
tool/structured-output support, retention/data authorization, latency, token usage and cost.
No current model name or price is hardcoded into the plan. Provider neutrality is an interface
goal, not a claim that multiple providers already work.

## Consequences and verification

Provider retries preserve logical operation IDs and budgets. Test transport errors, malformed
structured output, missing usage, rate limits, cancellation and successful-but-lost responses.
Run contract tests against fakes plus recorded, redacted provider fixtures; a fake success
cannot satisfy an integration milestone. Version adapter inputs and outputs. Do not leak
provider-specific orchestration objects into the domain or workflow history.
