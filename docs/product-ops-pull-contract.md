# Product Ops handoff contract, pull model (proposal)

Status: **proposed, 2026-10-01.** This is Delivery OS's side of roadmap Phase 2 and 3. It states
what DO-3, DO-5 and DO-6 need from Product Ops (PO-4, PO-5), so both teams can agree on it
before either builds. Nothing here is implemented. When both sides accept it, each item
becomes an ADR.

## Starting point

[PR #9](https://github.com/ahines99/agentic-delivery-os/pull/9) already has Product Ops
*push* a signed v2 envelope to `POST /handoffs/product-ops`. The verifier checks:

- a pinned Ed25519 key and the issuer;
- the audience `agentic-delivery-os`;
- the workspace, teams, onboarded repositories and policy versions;
- that the envelope expires at most one hour after it was issued.

It also re-reads the published ticket and requires its title, team and
CommonMark-equivalent description to match the signed plan.

The roadmap's DO-3 instead has Delivery OS *pull* the envelope when it sees a labelled ticket.
The proposal below keeps PR #9's verifier unchanged and adds only the retrieval path. **PR #9
has to be rebased and merged first**, because DO-3 depends on it.

## 1. Ticket reference (PO-4 writes, DO-3 reads)

Product Ops adds one line to every `delivery-ready` ticket, next to `Repository:`:

```
Handoff: sha256:<64 lowercase hex>
```

- The value is the digest of the approved specification. It is the same value PR #9 already
  takes in `X-Approved-Specification-Digest`.
- **The ticket carries no URL.** Delivery OS fetches from a configured Product Ops base URL.
  Ticket text never chooses a request destination, the same rule ADR-027 applies to GitHub
  links.

## 2. Retrieval (PO-4 serves, DO-3 calls)

```
GET {product_ops.base_url}/handoffs/{digest}
Authorization: Bearer <token from a configured environment variable>
```

| Response | Meaning | Delivery OS action |
| --- | --- | --- |
| `200`, body = signed v2 envelope bytes | Current approval | Verify with PR #9's verifier, then admit |
| `404` | Unknown digest | Hold (do not claim) |
| `410` | Expired, revoked or superseded | Hold; never run |
| Other or transport error | Unknown | Hold and retry next poll; never treat as approval |

- **Fresh signatures.** Product Ops signs a fresh envelope on each request, because of the
  one-hour lifetime. The approval inside it keeps its original issue time.
- **The token is read-only.** It can fetch envelopes and nothing else.

## 3. DO-3 behaviour

For a ticket that passes pickup contract v1 (ADR-036) and carries `Handoff:`, Delivery OS will:

1. Fetch and verify the envelope as above. The expected digest is the ticket's reference.
2. Re-read the ticket and require it to match the signed plan (PR #9's existing check).
3. Claim and admit through PR #9's `admit` path, keeping its inbox/outbox replay protection.

If any step fails, the ticket stays unclaimed and is retried each poll.

**Open question for Product Ops:** should a held ticket get a visible reason? DO-4 only
writes to tickets Delivery OS has claimed, so this would need a claim-then-hold state.

A labelled ticket **without** `Handoff:` is treated as hand-written work (PER-13, PER-14). It
keeps today's path: planning and plan approval under ADR-025.

## 4. Multi-ticket handoffs (DO-5)

PR #9 refuses `len(work_items) != 1` and any dependencies. DO-5 needs:

- **One envelope per specification.** It lists every work item, its ticket ID and
  `depends_on` edges by work-item ID. All tickets of one specification share the same
  `Handoff:` digest.
- **Admission is all or none, in one transaction.** A cycle, an unknown edge, or any ticket
  failing the match check rejects the whole set.
- **Scheduling.** A work item starts only after every prerequisite reaches `HUMAN_REVIEW`
  with a merged PR. Within one repository, ADR-033 already runs one delivery at a time.
- Each work item gets one workflow with a stable ID. A restart or redelivery resolves to it
  and never starts a second.

## 5. Cancellation and supersession (DO-6)

- Delivery OS re-checks `GET /handoffs/{digest}` each poll for specifications with
  unfinished work.
- **On `410`:** unstarted work items are never started, and the workflow records why.
  In-flight work finishes to a reviewable draft PR marked superseded, or is cancelled through
  the existing authenticated cancellation path. Effects already dispatched are reconciled,
  never replayed.
- **Product Ops needs a way to tell superseded from revoked.** Proposed: a `Reason:` header
  on the `410`, with value `expired`, `revoked` or `superseded`.

## 6. Progress back to Product Ops (PO-5)

DO-4 ([ADR-037](adr/ADR-037-linear-progress-reporting.md)) already posts in-progress, done and
blocked comments with hidden `delivery-progress` markers. PO-5 can read those, or Delivery OS
can expose a read-only status endpoint. Either way, Product Ops' own records stay
authoritative.

## Decisions requested from Product Ops

1. Accept the `Handoff: sha256:…` line and the configured-base-URL retrieval.
2. Choose how Delivery OS authenticates (proposed: a read-only bearer token).
3. Choose the `410` reason values, and whether held tickets get a visible reason.
4. Confirm the repository name Product Ops writes. This repo's GitHub name is
   `agentic-delivery-os`; its directory name is `agentic-delivery-engineer`.
