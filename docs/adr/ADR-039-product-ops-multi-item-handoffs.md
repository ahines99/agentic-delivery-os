# ADR-039: Multi-item Product Ops handoffs

Status: accepted, 2026-10-01; implemented as roadmap item DO-5. Not yet installed in the
local service.

## Problem

`admit` refused any signed specification with more than one work item or any dependency. Product
Ops publishes one ticket per work item, with `blocks` relations for dependencies, and every
ticket of one specification carries the same `Handoff:` digest
([pull contract](../product-ops-pull-contract.md), section 4). Product Ops needs no change for
DO-5: the envelope already lists every item, its dependencies and its ticket.

## Decision

- **All or none.** `admit` verifies the envelope once, then reads back every generated ticket
  before writing anything. One changed ticket rejects the whole specification. The verifier
  already refuses cycles, unknown edges and an item-to-ticket mapping that is not one to one.
  `Store.submit_handoff` then writes every item in one transaction.
- **One run per item, with a stable identity.** Each item gets a work record, run, start
  command and inbox receipt. The receipt is keyed `{digest}:{work item}`, with the work item
  ID `{specification}:{work item}`. Re-admitting the same envelope returns the same runs.
  A partly matching receipt set is a conflict. A changed revision still conflicts, as before.
- **Admission queues nothing.** Every start command is held without an outbox row.
  `linear_monitor.release_ready` runs after admission and on every monitor cycle. It queues a
  held start when all of the following hold:
  - every prerequisite run is in `HUMAN_REVIEW` with its change merged. A merged change is a
    publication observed as `MERGED` or `MERGED_UNVERIFIED`, or, for a documentation-lane
    run, a review head that is in the base branch;
  - the repository is not busy under ADR-033;
  - the repository still has `automatic_execution`.

  A release makes the repository busy, so independent items in one repository start one at
  a time. A held run does not count as busy itself, otherwise it would block its own release.
- **Claim only when released.** Product Ops asked that Delivery never claim a ticket only to
  hold it. `pull_handoff` returns "admitted", which allows the claim, only when the ticket's
  own item has been released. It returns "hold" while that item waits, which defers the ticket
  and keeps the cursor, as ADR-033 does. A ticket that quotes the digest but is not one of the
  handoff's tickets is never claimed.
- **No progress report while held.** DO-4 skips held runs, so an unclaimed ticket gets no
  comment, and the in-progress report is not marked as done before the claim.
- **Single-item specifications use the same path.** For them the change is only that the start
  is queued by the release step, which runs straight after admission.

## Consequences

- A prerequisite that ends `FAILED`, `CANCELLED` or `POLICY_BLOCKED`, or whose PR is closed
  unmerged, leaves its dependents held indefinitely, with their tickets unclaimed and the
  monitor cursor held. Stopping them for good is DO-6 (supersession and cancellation).
- A cancel command sent to a held run is not handled yet. The dispatcher signals Temporal,
  which has no such workflow. DO-6 covers this too.
- Release uses the settings and ticket text current at release time. Software work rechecks
  configuration in the dispatcher, and the documentation lane rechecks the ticket.
- The documentation capability still binds exactly one work item, so documentation
  specifications stay single-item.
