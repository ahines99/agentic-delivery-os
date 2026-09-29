# ADR-016: Explicit prospective campaign token ceilings

Status: accepted design, 2026-09-29. Implementation and activation remain pending.
This decision changes the prospective evaluation protocol; it is not an execution
grant, passing calibration, or completed campaign.

## Context

The goal requires independently scored real software tasks under equal finite
budgets. The v1 input reservation uses serialized request bytes plus 1,024. Repeated
full-source contexts can exceed its 100,000-input ceiling for small repositories:
one qualified development snapshot contains 80,629 bytes across 20 files. Baseline
and candidate evidence plus two independent scorers can be infeasible before a call.

The original token ceilings were project protocol choices. Revising them is a
material experimental change and must be prospective and preregistered. No historical
campaign has been frozen or scored. Earlier failures and costs remain evidence and
cannot be relabeled under this decision.

## Decision

Add explicitly selected `agentic-historical-v2` with maximum **500,000 total input
tokens** and **64,000 total output tokens** per attempt. Preserve **USD 5 model**,
**USD 1 infrastructure**, **1,800 seconds active wall time**, existing command,
repair and retry maxima, and **USD 1,000 total campaign cost including preparation
and repeats**. Both comparison arms share identical frozen limits. Building,
review, correction, final scoring and any authorized adjudication use the same
original attempt account and deadline.

Keep original `AttemptLimits`, v1 arm/specification/policy types, defaults, schemas,
serialized bytes and digests unchanged. Direct v1 parsing must still reject 100,001
input or 20,001 output tokens. Add named v2 limit, arm, specification and policy
contracts with explicit tags and shared exact dispatch. Never select v2 because v1
parsing failed or numeric limits are large. Reject mixed campaign/arm/policy protocols,
including v2 with smaller numeric limits paired with v1 authority.

Only the schema-3 execution campaign may carry the explicitly tagged new protocol.
Legacy freeze/inspection and CLI schema defaults remain v1. Grants already bind exact
campaign, arm and policy identities. No existing grant, account, qualification, task
manifest or frozen artifact is rewritten. Every live and read-only consumer resolves
the pinned protocol. Fresh inspection authority cannot upgrade old execution.

Preserve request forecasts, rate binding, reserve-before-call accounting, actual
settlement, retained unknown outcomes and summed reservation before either initial
scorer runs. Preserve the 512 KiB semantic context ceiling and full source evidence.
A lossless context codec is an independent intervention needing explicit wire/prompt/
configuration bindings and matching calibration. Token estimates, omitted evidence
and reference-only placeholders do not replace these controls.

## Cost and feasibility

At the development configuration's frozen example rates of USD 5 per million input
and USD 25 per million output tokens, the maxima imply USD 4.10 model cost:
`500000 * 5 / 1000000 + 64000 * 25 / 1000000`. This is arithmetic, not a current-price
claim or unconditional invoice guarantee. Per-call rounding and different applicable
rates remain subject to the USD 5 ledger stop. Unpriced requests are denied.

Campaign reservation still uses USD 6 per attempt, not USD 4.10. Thirty tasks with A/B
and prescribed stability repeats reserve USD 504 for 84 attempts; 36 tasks reserve
USD 576 for 96 attempts. Remaining capacity covers preparation, including earlier
failed and uncertain operations belonging to the program. A new protocol cannot
reset program cost or erase reservations.

Larger contexts, repairs and latency may still exhaust limits. Two 20,000-output
scorers reserve 40,000 tokens; a complete repair path may not fit. A prospective
6,000-output configuration permits a 54,000-output envelope across nine calls, but
arithmetic establishes neither adequate quality nor input/deadline feasibility.
Each configuration requires matching successful calibration. Current failed scorer
calibrations remain failed.

## Activation and evidence

Require v1 schema/serialization regression tests; v2 exact boundary tests; mixed and
unknown protocol rejection; unchanged money/time/repair limits; one-account allocation,
candidate, deterministic and semantic execution checks; and original-policy
reconstruction by read-only consumers. Verify aggregate reservations, rate refusal,
current authority, unchanged task bytes and full-corpus cost/split invariants.
Source and tests alone do not authorize paid execution.

Keep target 36/minimum 30 tasks, at least three repositories, equal grouped development/
validation/sealed splits, stability repeats, contamination disclosures, strict
denominators and all promotion gates. Freeze the protocol before scored runs; report
it with results and do not pool v1/v2 as equal experimental conditions. No calibration,
historical scoring, corpus admission, human benefit, publication or pilot signoff
follows from this ADR. Human product plan approval and merges remain unchanged.

## Alternatives

Keeping v1 and selecting only tiny eligible tasks remains possible, but corpus
feasibility is unproven. Smaller output settings and lossless deduplication may help
either protocol but need separate calibration. Replacing conservative forecasts with
estimates or raising money, wall-time or campaign caps is outside this decision.
