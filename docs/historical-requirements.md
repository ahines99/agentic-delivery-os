# Protected issue requirements acquisition

`evaluation.historical_requirements.acquire_public_issue_requirements` captures the
exact current Markdown body of one explicitly selected public GitHub issue, along with
provider-reported edit chronology. It is a separate evaluator research capability,
not a product publication broker, task admission, or historical benchmark result.
No actual historical issue payload was fetched while implementing its synthetic tests.

The function accepts `IssueRequirementsRequest(repository, issue_number, accepted_at)`
and an explicitly supplied `SecretStr` research credential. It performs exactly three
read-only GraphQL queries at `https://api.github.com/graphql`: public repository metadata,
then two copies of the same issue/body/edit query. It rejects private repositories before
requesting issue content and rechecks repository visibility and IDs in both captures.
The repository name, node/database IDs, issue node ID/number/type and URL must agree.
PRs, GraphQL errors, null/unknown metadata, redirected responses and changing captures
are refused. No token lookup, `gh` subprocess, product credentials, implicit PAT fallback,
environment proxy, retry, browser scraping, or arbitrary query is implemented.

The trusted private caller may explicitly supply an operator-authorized research
credential. That credential only goes to the fixed endpoint and is never placed in an
artifact, result, or exception message. It is not evidence of rights clearance or authority
to use personal/third-party content in a campaign. The injected HTTP client is a trusted
transport/test dependency; custom transports and hooks remain trusted code. Its default
auth, headers, cookies and query parameters are not inherited by the explicit request.

GitHub's REST issue API provides a current body and update timestamp; its Issues endpoints
can also return pull requests. This implementation does **not** treat an `updated_at`
value as edit-history proof. The GraphQL Issue schema instead exposes nullable
`lastEditedAt`, `editor`, `includesCreatedEdit`, and `userContentEdits`. GraphQL calls
use explicit authentication. [REST issues](https://docs.github.com/en/rest/issues/issues#get-an-issue),
[GraphQL Issue fields](https://docs.github.com/en/graphql/reference/issues#issue),
[GraphQL authentication](https://docs.github.com/en/graphql/guides/forming-calls-with-graphql).

Two narrow chronology interpretations are supported:

- `PROVIDER_REPORTS_NO_EDITS`: `lastEditedAt` and `editor` are explicitly null,
  `includesCreatedEdit` is false, and the non-null edit connection reports exactly zero
  nodes, zero total count, and no next/previous pages. The provider's issue creation
  timestamp is used as `requirements_as_of`.
- `PROVIDER_REPORTS_PRE_SOLUTION_EDITS`: a non-null last-edit timestamp is corroborated
  by a complete, nonempty connection of at most 100 distinct edit nodes. None may be
  deleted. All reported edits must lie between issue creation and the last-edit time,
  and their maximum timestamp must equal that last-edit time. That timestamp becomes
  `requirements_as_of`.

Both require `issue_created_at <= requirements_as_of < accepted_at <= captured_at`.
`updatedAt` must be valid and no earlier than creation/edit time, but may follow
acceptance because it is not used as a body-edit timestamp. The supplied `accepted_at`
is a trusted caller input; this function does not fetch or establish the accepted
solution commit or its acceptance time.

These are **inferences from the provider's current reported history**, not independent
archival proof that ancient text never changed. GitHub documents nullable edit fields,
a total count for the edit connection, and `deletedAt` on edit nodes; it does not promise
an immutable, exhaustive historical archive to this client. Unknown, hidden, missing,
paginated, deleted, contradictory or post-acceptance edit metadata is refused. Two
identical captures catch observed races, not all possible edits between reads or after
capture. Returned records explicitly retain `archival_proof=false`, `rights_cleared=false`
and `admitted=false`. [Edit connection and deletion metadata](https://docs.github.com/en/graphql/reference/users#usercontentedit).

The raw body is preserved byte-for-byte as UTF-8 in a protected artifact. The current
title is preserved in a **separate** artifact marked
`CURRENT_TITLE_NOT_HISTORICALLY_VERIFIED`; body edit history does not establish title
history. Do not silently promote that title into historical requirements. Comments,
edit diffs, authors, actor logins, emails and personal profiles are not queried.
`editor { __typename }` records only null-versus-present semantics, and the persisted
projection contains only `editor_present`. The protected evidence artifact includes
issue/repository identity, timestamps, edit-node IDs/timestamps, content digests, fixed
query/request digests and three raw-response digests. Raw response documents are not
stored; the response digests bind transport bytes without copying unexpected metadata.
Only references and allowlisted metadata are returned to the caller.

The hard limits are three requests, 256 KiB per response, 768 KiB total responses,
32 KiB of nonempty body text, 4 KiB of title, and 100 edit nodes with no pagination.
Default request/overall deadlines are 15/60 seconds, with hard ceilings of 30/120 seconds.
Callers can lower response/body limits. Redirects, compressed responses, duplicate JSON
keys, binary control characters, invalid lengths, 403/429, and exceeded limits fail
without partial success. No artifacts are written before all three responses and all
checks pass. An I/O error between content-addressed writes can leave an unreferenced
protected artifact, but cannot return an acquired result.

The caller must supply nonempty `worker_roots` covering all relevant source checkouts,
worktrees and worker scopes; protected storage must be disjoint in both directions.
This explicit scope boundary is not filesystem discovery or authentication. Artifacts
remain outside interactive implementation-agent context and campaign inputs. ADR-010
permits only the separately authorized protected evaluator to inspect them.

This capture is complementary to baseline acquisition. Combining it with a baseline
still does not provide oracle/reference acquisition, semantic requirements validation,
license or privacy clearance, independent qualification, or campaign admission.

## Recorded protected capture

On 2026-09-28, the integrated acquirer captured issue 405 from `tkem/cachetools`
using an explicitly supplied operator research credential. The three fixed queries
transferred 7,403 bytes; the preserved issue body contains 2,956 UTF-8 bytes.
Both captures reported the strict no-edit combination, with creation/as-of time
2026-07-18T18:15:55Z preceding the supplied acceptance time 2026-07-30T15:27:00Z.
The body, current title and chronology evidence remain in protected evaluator storage.

A cached read revalidated the result and artifact bindings with zero network calls.
No body/title text was printed, repository code executed or model called. Status is
`PROVIDER_REPORTED_PRE_SOLUTION_BODY`, with archival proof, rights clearance and
admission all false. This does not verify the current title's historical wording or
close the remaining reference/oracle, runtime and qualification requirements.
