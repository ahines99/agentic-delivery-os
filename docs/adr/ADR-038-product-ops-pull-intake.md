# ADR-038: Pull intake for signed Product Ops handoffs

Status: accepted, 2026-10-01; implements roadmap DO-3 under the agreed
[pull contract](../product-ops-pull-contract.md) (Product Ops ADR-028). Not yet installed in the
local service.

## Decision

A Linear ticket that passes pickup contract v1 (ADR-036) and carries a `Handoff:` line is
Product Ops work. It never enters normal Linear intake. Each poll, the Linear monitor:

1. **Parses the reference.** It requires exactly one bare digest (an optional `sha256:` prefix
   is accepted). A URL, a malformed value, or two different digests stops that version of the
   ticket.
2. **Skips already-admitted work.** If an inbox record already holds this digest, the monitor
   only makes sure the ticket is claimed.
3. **Holds while the repository is busy.** If another delivery is in progress for the
   repository (ADR-033), the ticket is held without being fetched or claimed.
4. **Fetches the envelope.** It calls `GET {product_ops.handoff_base_url}/handoffs/sha256:{digest}`
   with the read-only bearer token from `product_ops.handoff_token_env`.
   - The host comes only from configuration, never from the ticket.
   - Plain HTTP is accepted only for `127.0.0.1` or `localhost`.
   - Redirects are not followed, and the response size is bounded.
   - `404`, other statuses and transport errors **hold** the ticket for retry. `410` **stops**
     it; the `superseded` or `revoked` reason is logged.
5. **Admits through PR #9's `admit`.** The pinned Ed25519 key, issuer, audience, workspace,
   teams, repositories, policy versions, freshness and the CommonMark read-back of the ticket
   all apply unchanged. Admission is idempotent: the inbox stores the envelope, and a re-signed
   envelope is a duplicate, not a second authorization.
6. **Claims the ticket last.** The ticket is assigned only after admission succeeds. A held or
   refused ticket is never claimed and gets no visible reason.

The pull path admits with `actor=None` and records `admitted_by: product-ops-monitor`, a reserved
system identity. Here the pinned signature is the authority. The existing push path still
requires an authenticated operator.

The retrieval URL and token variable are excluded from the execution digest.

## Consequences

- **This PR carries only the verifier and the intake.** PR #9's documentation execution lane is
  not part of it.
  - Admitted documentation-type work therefore reaches the standard workflow, where intake
    policy blocks it, and DO-4 reports the reason on the ticket.
  - Admitted software work goes through planning and waits for authenticated human plan
    approval. ADR-025 automatic approval applies only to `linear` work.
- **DO-4 reports Product Ops runs too.** It finds the ticket through the admitted inbox record,
  and adds an "in review" comment when such a run reaches `HUMAN_REVIEW` without a hosted PR.
- **Integration point Product Ops must confirm.** The ticket read-back compares the live ticket
  with the description in the signed plan. The `Repository:` and `Handoff:` lines must
  therefore be part of the signed, published description. A line added after signing makes
  admission refuse the ticket as changed.
- **Single item only.** Multi-item specifications are still refused by `admit`. DO-5 adds
  all-or-none admission.
