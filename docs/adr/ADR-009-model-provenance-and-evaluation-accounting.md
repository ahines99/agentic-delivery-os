# ADR-009: Bound model-operation receipts and separate evaluation accounting

Date: 2026-09-28. Status: accepted implementation decision. This supplies prerequisites
for agent-led qualification; it does not admit tasks or authorize benchmark spending.

## Problem

The model adapter retained parsed output and total workflow accounting, but lacked
durable actual token counts and timing for an individual request. A cached operation
could also return output after its caller changed the prompt or context. Neither behavior
supports an honest provenance record for an independently executed qualification agent.

Evaluation preparation must not manufacture a product delivery workflow or plan approval
merely to obtain its budget ledger. Its storage and checkpoints need their own scope.

## Decision

The broker writes a typed settled-operation receipt with account and operation IDs,
provider response/message object ID, requested and returned model names, UTC request/response-processing
timestamps, actual reported token counts, configured prices and calculated cost. Digests
bind the instructions, task context, output schema, exact constructed request payload,
model configuration and parsed output. The receipt contains neither request headers nor
raw prompts/context. Parsed output remains private in the existing settlement result.

The receipt and output commit with settlement. A lost acknowledgement can recover that
same receipt without another model call. Cached recovery validates account ownership,
settled accounting, reservation ceilings, result identity and every current request
binding before returning output. Changed requests must use a separately authorized
operation; they cannot silently reuse an old result or reissue the old operation.

The broker also retains a separate allowlisted observation before interpreting a returned
HTTP response, or when transport failure/cancellation interrupts the call. It includes response
status/digest, available object/model IDs, recognized termination, and valid reported token counts;
unobserved values remain absent. It contains no raw body, error text or request headers. The first
observation is immutable and survives settlement. It does not settle costs, authorize a retry or
turn malformed output into a model receipt. A process crash before observation can still leave
only a reservation; historical missing observations are not reconstructed.

Delivery storage exposes a trusted internal receipt read. Legacy operations remain
present with their original cost/output, but absent per-call provenance stays absent.
They cannot be upgraded into new receipts from aggregate usage, assigned fictional
timestamps or automatically reissued. Cached recovery without bound provenance fails
closed. Existing Temporal history replay does not execute an activity to fabricate it.

A separate evaluation ledger implements the same reserve/settle/read interface in a
dedicated database. Its accounts and immutable checkpoints are distinct from delivery
workflows, command inbox/outbox and human approvals. Creating an account establishes
a finite ceiling, not permission to send repository data, spend money or admit a task.

## Limits

These records originate in the trusted controller, not a model's claim that it ran.
Hashes establish byte identity, not protection against a writer who can modify the
private database or artifact store. Configuration digests exclude actual credential
values; rotating a key does not claim a new model identity.

Reported token usage and configured rate-card arithmetic are not an independently
reconciled provider invoice. Provider aliases can change; requested and returned names
are retained without inventing an immutable snapshot identity. The body object's ID is not
represented as an HTTP request correlation header; that header remains unmeasured. An uncertain operation
keeps its reservation and has no settled receipt. Invalid responses are sanitized and
cannot become qualification evidence. Process-loss reconciliation, calibration, twelve
oracle runs, independent semantic reviews and campaign orchestration remain separate work.
