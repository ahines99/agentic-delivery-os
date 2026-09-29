# ADR-020: Reserve shared program capacity before account creation

Status: implemented prospectively, 2026-09-29. No live ledger enrollment or paid execution.

## Problem

Per-account limits and a census of declared ledgers do not atomically enforce a total
evaluation budget. Two independent preparation/execution ledgers can each admit work while
their combined liability exceeds a program cap. Summing snapshots before a call races with
another controller. Releasing a reservation after a crash can double-spend unknown work.

## Decision

Use one local `ProgramBudgetRegistry` for a prospectively configured single-tenant evaluation
program. Its immutable policy pins the program ID, approved accounting-authorization digest,
finite cap (at most the protocol's USD 1,000 limit), and up to 64 approved ledger targets.
The trusted controller's current guard supplies actual accounting permission; a serialized
policy or digest does not authenticate itself or authorize a provider call.

Program-bound `EvaluationExecutionStore` instances use explicit ledger schema 2. Their
binding pins the registry identity and enrolled target nonce. Schema-1 ledgers remain
unchanged and cannot be relabelled or implicitly migrated into this new scope. Old clients
refuse the additional schema/marker. A current client may open a bound ledger without the
registry for metadata reads, but new account creation and reservations require the matching
concrete registry. Cached settled results and original settlement remain available.

Before creating a local account, reserve its maximum possible monetary liability in the
registry: model ceiling alone, or the smaller of the shared ceiling and model-plus-infrastructure
ceilings. All accounts across all enrolled ledgers compete in one SQLite `BEGIN IMMEDIATE`
transaction. Account IDs are unique across the program. Existing monetary, token, deadline,
data and execution grants retain their own checks; registry capacity does not replace them.

The account envelope progresses `HELD -> ACTIVE -> CLOSED`. A failure before local account
creation or activation retains the full hold. New reservations require ACTIVE plus a local
OPEN marker. Idempotent creation can complete the same interrupted activation; it cannot
recreate a missing ACTIVE account or redirect its budget to another target. More than 10,000
envelopes is refused rather than truncated. Missing/corrupt policy, schema, identity or capacity
blocks new work. Registry file replacement is detected on an existing handle.

## Closing and uncertainty

Settlement alone does not release unused envelope capacity. `close_program_account` locks
the local account, requires zero unresolved operations/reserved balance, and irreversibly
closes new reservations. The registry then obtains concrete closure proof from that exact
store and verifies actual operation costs against the account counter before reducing the
envelope to settled spend. A caller-supplied amount or serialized proof cannot release funds.
Neither API reopens CLOSED accounts. A model/infrastructure reservation racing with closure
either wins before closure (which then refuses unresolved usage) or observes the closed fence.

If local closure succeeds but registry reconciliation fails, the local fence persists and the
registry retains the full envelope. Repeating closure can reconcile those same facts without
spending, deleting uncertainty or granting another attempt. Unknown usage cannot close.
The coordinator/driver must deliberately close only a finished account: closing before an
optional adjudication tail prevents that tail and does not create a replacement grant.

## Trust, deployment and remaining scope

The registry is a local SQLite coordination service used by trusted controller processes on
one host, not a multi-host distributed database. Its files and ledger owners remain trusted.
Hashes, nonces and schema checks detect accidental/mismatched state; they do not authenticate
a malicious administrator or make restoring inconsistent database backups safe. Permission
revocation is checked around registry transactions; settlement never silently releases holds.

This enforces future enrolled account envelopes. It is not a complete invoice, measured total
cost report, or proof that historical/pre-registry costs and every external ledger were
declared. Historical liability incorporation, campaign-required enrollment, whole-program
report reconciliation and cost promotion remain required before closing that release gate.
No prior calibration, qualification, campaign, grant or ledger was migrated or renewed here.
The [operating contract](../program-budget.md) describes the API and verification scope.
