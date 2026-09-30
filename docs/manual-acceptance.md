# Manual acceptance on a draft PR

An explicitly manual acceptance criterion is preserved as a human check. The builder
does not map it to pytest, and the independent model reviewer must report UNKNOWN
for it. Passing automated checks can produce a draft PR with the manual criteria
marked PENDING. The workflow waits in ACCEPTANCE_CHECK; it cannot update Linear to
In Review until the required human decision and exact-head CI are both current.

This implementation is under qualification on the manual-criterion development
branch. It is not yet installed in the local service. The existing automatic path
continues to serve the configured repository.

## Submit a decision

Inspect the draft at its exact head revision. Use the existing authenticated
control-plane API to read the decision binding:

```text
GET /workflows/{workflow_id}/manual-review
Authorization: Bearer <operator credential>
```

The response includes `binding` and the pending criterion IDs. Repository read access
is required. After actually checking each criterion, create a JSON object containing
all fields from `binding` and a `criteria` array with one decision for every pending
criterion. Each entry has `criterion_id`, `result` (PASS or FAIL), and a nonempty
`evidence` explanation, limited to 4,096 characters. Do not include an actor identity;
the API derives it from authentication. Do not put credentials or private unrelated
data in the evidence explanation.

Submit the completed object using a new stable idempotency key:

```text
POST /workflows/{workflow_id}/manual-review
Authorization: Bearer <operator credential>
Idempotency-Key: <unique decision key>
Content-Type: application/json
```

The authenticated operator needs both operator and reviewer roles for the repository.
The HTTP 202 receipt means queued, not accepted. Read `/commands/{command_id}` for
APPLIED or REJECTED and `/workflows/{workflow_id}` for the workflow outcome. Repeating
the same request and key refers to the existing command while its context remains
current. A key reused for a different decision is rejected.

## Readiness and recovery

The command binds repository, base/head revisions, input, evidence manifest, policy,
configuration and workflow sequence. It must cover the complete manual set exactly
once. Authority and `approval_validity_seconds` are rechecked when consuming the
command and before the final handoff. The plan approval must also remain valid.
Automation identities cannot submit a human decision. Model PASS claims, missing
evidence, duplicate criteria, stale revisions and revoked/expired reviewers cannot
establish acceptance.

A failing decision blocks the workflow and retains the draft. The human wait uses
`human_wait_seconds`; expiry blocks the workflow. Authenticated cancellation remains
available while waiting. Restart preserves the same workflow and pending command;
it does not renew authority or start another budget. A changed context requires an
explicit subsequent attempt rather than accepting an old approval against new code.

After a passing decision, required CI is reconciled against the exact published head.
The GitHub App updates only the generated evidence section, records human PASS results
with a digest of the private acceptance record, and preserves surrounding PR notes.
It keeps the PR draft. Changed generated text or revisions require reconciliation.
An unavailable update response permits one read-back, not a repeated mutation. If
the result cannot be confirmed, the workflow retains an UNKNOWN result and does not
perform the Linear handoff. Current human, plan and CI authority is checked again
before that handoff. Human merge review remains separate.

GitHub supports this through its [PR update endpoint](https://docs.github.com/en/rest/pulls/pulls#update-a-pull-request)
and [repository-scoped installation tokens](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app).
The evidence-update token requests only Pull requests write permission for the
configured numeric repository, and the adapter revokes it afterward.

The controlled qualification uses owned synthetic reviewer identities and provider
responses. Those tests are not evidence that a real human has accepted a ticket or
approved the pilot. See [ADR-030](adr/ADR-030-pending-manual-acceptance.md).
