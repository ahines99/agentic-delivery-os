# ADR-010: Executed qualification stages and protected semantic review

Date: 2026-09-28. Status: accepted implementation decision. These stages are prerequisites
for an integrated autonomous qualifier, not a completed benchmark or admission protocol.

## Problem

The v1 record validator checks twelve deterministic executions, but its model review
context contains summaries and opaque references. A model cannot assess whether tests
capture the requested behavior from a digest. An adjudicator cannot resolve substantive
disagreement without seeing the two actual findings. Flags claiming calibration likewise
do not establish that any calibrated execution took place.

Execution also consumes infrastructure. Charging Docker work through fictional model
tokens, ignoring cleanup, or releasing an uncertain reservation would understate cost.

## Decision

Use three explicit, independently verifiable stages:

1. A deterministic runtime revalidates protected preparation, executes preflight and
   twelve clean baseline/reference checks, preserves exact collector receipts and records
   measured infrastructure duration. Current authority and absolute deadlines apply during
   work; cancellation retains ownership of cleanup. The stage never admits a task.
2. A protected v2 review context supplies actual authorized pre-fix source, oracle tests,
   requirements, supporting provenance and normalized execution outcomes. Initial reviewers
   use distinct contexts without peer outputs. The optional adjudicator receives both sealed
   outputs and must resolve each differing finding. Reference solutions, raw execution output
   and controller credentials are excluded. All criteria and eligibility dimensions require
   findings citing inspectable included evidence. The stage never admits a task.
3. Executed development calibration binds frozen fixtures, expected decisions/findings,
   rubric, prompt, output schema, model configuration and actual settled model receipts.
   Trusted allowlists authorize the exact frozen cases and configuration. Expected answers
   stay evaluator-only. Results recompute agreement, false admits, mandatory failures and
   measured usage; declared booleans cannot substitute for executions. Calibration never
   admits a historical task.

The evaluation ledger adds opt-in model/infrastructure/shared cost ceilings using its
existing schema. Infrastructure operations reserve zero model tokens and bind immutable
inputs, duration ceiling and rate card. Settlement uses measured elapsed milliseconds;
overrun or unknown outcome remains reserved. Local rates are configured estimates, not
independently reconciled invoices. Several accounts still require campaign-level allocation.

The no-answer-leakage rule continues to cover implementation-agent conversation, campaign
builders/reviewers, public exports and tuning against sealed cases. Explicitly authorized
qualification evaluators need oracle visibility inside the protected execution boundary;
this does not grant any other agent that access. Source and oracle inputs are bounded in
full and rejected when oversized, not silently truncated. Trusted supporting prose remains
a producer responsibility; structural validation cannot prove absence of paraphrased answers.

## Compatibility and limits

The existing v1 record inspection/admission path remains unchanged in this stage. No v1
record gains v2 status by default. The new v2 review API accepts v1 deterministic input
contracts as a source of execution facts, not proof of completed semantic admission.

The integrated qualifier must still bind current preparation, the trusted deterministic
runtime checkpoint, exact executed calibration and independently metered reviews into one
new admission record. It must migrate worker/scorer/campaign dispatch explicitly and reject
mixed protocol chains. Standalone `admitted=false` results cannot be relabeled as admission.
No historical candidate is qualified by these changes. Model quality, rights clearance,
hostile-code attestation, historical performance and human benefit remain separate claims.
