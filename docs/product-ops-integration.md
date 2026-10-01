# Product Ops integration

The [PER-7 validation record](records/2026-09-30-product-ops-handoff.md) contains the actual live result,
verification boundary, replay evidence and reproduction commands.

Product Ops accepts a prompt and repository name, produces requirements and proposed Linear
tickets, obtains human approval, publishes them, and signs a v2 handoff. Delivery accepts approved
work into its own database and owns execution. The services do not share persistence models.

The optional `product_ops` configuration pins `issuer`, `key_id`, `public_key_hex`, `workspace`,
`teams` and `policy_versions`. Repositories must also be explicitly onboarded in Delivery.
Without this configuration `/handoffs/product-ops` is disabled. Requests require the existing
operator bearer token plus `X-Approved-Specification-Digest`; the body is the signed envelope.
Linear reads use `LINEAR_API_KEY`. No Jira or OAuth integration is added.

Admission validates the public contract and rereads the generated issue. Its exact title,
team and ID, and CommonMark-equivalent description, must match the signed publication plan.
The bounded, pinned parser preserves content, code, links and structure; only presentation
aliases are accepted. Signed bytes and approval digests are never normalized. The original envelope is
retained in Delivery's inbox alongside its transactional work record and start outbox. Acceptance
is not evidence that execution has completed. Replayed envelopes cannot duplicate execution.

The controlled documentation lane additionally installs a strict `documentation_capability`
and `documentation_approvers`. The capability's policy hash, semantic binding, pinned Git base,
path and complete inert content must match. A configured current reviewer must match the signed
human approval. The dispatcher produces only a local review branch and content-addressed local
change request. HUMAN_REVIEW is its final state, reached through legal lifecycle edges only;
merge remains human. See
[ADR-034](adr/ADR-034-product-ops-documentation-handoff.md).

The initial consumer accepts one work item and refuses multi-item dependencies or replacement
revisions. Generic software work retains the existing planning and human approval gates. A general
prompt-to-many-ticket execution service needs atomic batch admission, dependency scheduling,
supersession and cancellation propagation before it can be described as autonomous.

PER-7's current integration uses a separate private Delivery profile with a $3 model ceiling,
no model configured, a local SQLite database and a pinned documentation capability. Product Ops
has a separate $2 allocation under the combined $5 authorization. The documentation executor
requires no paid API calls. Actual PER-8 was admitted as workflow
`f109d0c5-ee2b-43e3-8cea-159aacbe3dc6`, reached HUMAN_REVIEW, and created commit
`b44c681ffa1df5fe0094520219a283416e35239b` on the approved target base `d960488`.
The change request is OPEN/UNMERGED; the diff adds only `docs/pilot-success.md`, exactly 98
bytes with SHA-256 `26fc9bf3cefc5e743f0e8d71c17d617608b48e48bad692f78811d86b511a1b2d`.
Repeat execution returned the same result, with one run, inbox and start outbox. Target main
remains clean and unchanged. No hosted PR, push or merge was authorized or performed.

Tests use explicitly synthetic signed publication receipts and mocked read-only Linear responses,
but exercise actual Delivery storage and actual Git object/ref creation in disposable repositories.
They are not evidence of live Linear publication, hosted PR creation or production availability.
