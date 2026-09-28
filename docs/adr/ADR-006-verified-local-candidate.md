# ADR-006: Verified local candidate before remote publication

Status: accepted implementation refinement. Date: 2026-09-27.

The implementation now runs the bounded builder, fresh-container validation, criterion-specific
tests and independent model review before creating a GitHub draft PR. This reduces remote churn
and keeps failed candidates local. `LOCAL_REVIEW_READY` is a candidate result, not a delivery
lifecycle state and not a claim of a published PR. The durable workflow records the result while
validating, then publishes through the GitHub App broker. If publication is disabled it terminates
`POLICY_BLOCKED` with the candidate evidence retained. It never substitutes a personal token.

For the initial controlled pilot every execution requires an authenticated plan approval, including
low-risk work. That approval binds the input digest, workflow sequence and a plan artifact containing
the base commit and snapshot digest. Source changes after planning do not enter the candidate;
the publisher independently checks whether the remote base has moved.

The draft PR is the human handoff. It stays draft until a human has reviewed it; this supersedes the
earlier automatic-ready recommendation. All merges stay human. Deployment remains outside scope.

Temporal records the coarse lifecycle. The long candidate activity records per-operation model
usage and immutable execution artifacts, heartbeats, obeys a finite wall-clock limit and performs
bounded internal correction. It is not retried automatically: an unknown provider outcome retains
its reservation and requires reconciliation rather than a duplicate billable generation. This is
conservative recovery, not an exactly-once claim. More granular resumable build activities remain
an operational-hardening task before broad unattended use.

An available Anthropic account allowed an actual development run with `claude-opus-5`; the existing
OpenAI wire adapter is covered by contract tests but has not been exercised live. This is a practical
development selection, not a completed benchmark-driven provider comparison. Generation uses the
official [Anthropic structured output contract](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
and recorded [pricing](https://platform.claude.com/docs/en/about-claude/pricing) checked 2026-09-27.
The OpenAI adapter follows [Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Docker Desktop is the verified local runtime. Jobs have no host mount, Docker socket, provider
credential, or network; read-only image plus bounded tmpfs holds candidate files. This remains a
single-tenant controlled-repository design, not a hostile multi-tenant isolation guarantee.
