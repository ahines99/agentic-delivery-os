# Independent GitHub CI evidence

`integrations/checks.py` implements strict, pure check-run projection and readiness evaluation.
It contributes to M3-03's exact-revision evidence gate; it does not authenticate deliveries,
fetch GitHub state, persist events, authorize merges, or establish that a live integration has
passed. The connected API/storage projection and authenticated REST broker are implemented
and fixture-tested separately. Product GitHub App keys are not available for live validation.

## Trusted input and producer identity

Call `parse_check_run(payload, repository_id=..., installation_id=...)` only after validating
the HMAC against the exact raw body and authorizing the configured installation and repository.
The expected numeric IDs come from operator configuration. The parser checks them again against
the signed body and projects the run ID, suite ID, exact head SHA, check name, producing App ID,
status, conclusion and timestamps. It accepts `created`, `completed`, and `rerequested` events.
Webhook headers, sender names, App slugs, report text and supplied attempt counters grant no
authority. Unknown display fields are discarded, not interpreted as policy.

Each `RequiredCheck(name=..., app_id=...)` pins one exact name to one permitted producer App.
The webhook receiver's installation ID is distinct from the producer's App ID. A same-named
check from another producer cannot satisfy or overwrite the configured check. Changing the
required-check policy must invalidate prior policy-bound readiness.

## Two results, with different meanings

`evaluate_checks(repository_id=..., head_sha=..., required=(...), observations=(...))` returns:

- `observed_ready`: all currently supplied evidence satisfies configured checks, without any
  known conflicting or pending attempt. This is provisional for webhook observations.
- `ready`: the observed requirements pass **and** the trusted caller provided a complete fresh
  provider reconciliation. The default is false until `reconciled=True` is explicitly supplied.
- `reconciliation_required`, deterministic `reasons`, and `selected_run_ids` for the read model.

An empty required-check policy fails closed. Only `completed` plus `success` satisfies a check;
skipped, neutral, cancelled, failed, timed-out, stale, action-required and incomplete results do
not. Exact numeric repository and head SHA matching are mandatory. In particular, a check for
a synthetic merge commit does not silently count as evidence for the PR head commit. Such
checks require a separately explicit target/merge-base evidence contract.

## Reruns and out-of-order delivery

Duplicate observations of the same result are idempotent. For one run ID, an older queued
observation cannot erase an unambiguous completed result. Conflicting terminal facts, changed
immutable identities, or reused IDs with a different start require reconciliation. Across
different IDs, only one uniquely newest start timestamp can supply the result; an unknown
timestamp or tied newest attempts blocks readiness. Numeric IDs and arrival time are never
treated as provider attempt sequence numbers.

`rerequested` invalidates the affected observation set even when its payload still says
`completed/success`. Do not merge historical webhook facts into a fresh REST snapshot. Fetch
and replace the current projection under a reconciliation generation, retaining the event
history separately for audit. An event that arrives during reconciliation must invalidate or
restart the snapshot using an inbox/version comparison; setting a boolean after a stale fetch
is insufficient.

## Integration contract for the authenticated broker

Before setting `reconciled=True`, the caller must:

1. Authorize the current repository/installation and read the PR's exact head and base.
2. Fetch every page of check runs for the exact head SHA using `filter=all`, including incomplete
   and earlier attempts; the pure evaluator selects an unambiguous latest attempt by start time
   for each configured name/App pair. The broker permits at most 2,000 rows across 20 pages of
   100. Require two identical complete snapshots and stable totals; reject truncation, duplicates,
   missing pages, foreign head SHAs, ambiguous attempts, revocation or API failure. Check-suite
   state is also reconciled so an old successful run cannot hide a pending suite rerun.
3. Project each returned run using `parse_check_run_response(run, repository_id=...)`. Only this
   trusted REST path creates normalized observations with `action="reconciled"`; the webhook
   parser rejects that action. An individual response alone does not prove snapshot completeness.
4. Re-read the PR and compare head/base and the inbox/version watermark. Atomically persist the
   reconciled snapshot with repository/head, policy/configuration digest and its invalidation
   generation. Only evaluate the complete current snapshot. New events and revision/policy
   changes revoke it. Never accept `reconciled` from request or webhook JSON.
5. Combine this result with the existing candidate-manifest, human-approval and independent-review
   gates. This module cannot mark a PR ready, merge it, or bypass repository rules.

GitHub Actions checks from an allowed App/name remain dependent on protected workflow definitions
and repository governance. App identity alone does not prove that a compromised workflow performed
the intended tests. The builder must not be permitted to change those definitions.

## Durable ingestion and the read API

The GitHub webhook endpoint routes from the signed body after HMAC and installation/repository
authorization. Check-run projections and inbox receipts commit atomically. New unique evidence
increments a repository/head generation and invalidates its cached snapshot; replaying identical
signed bytes with a changed unsigned delivery ID does neither. Suite `requested`, `rerequested`
and `completed` events invalidate that head too; no suite result substitutes for individual checks.
Keep authenticated polling enabled: a read-only App subscription does not receive every rerun
action. Publication observations also check repository IDs/names, branch refs and draft state,
not only the two commit SHAs. PR-number lookup still finds a managed PR whose head ref changed.

`ci_generation` captures the pre-fetch watermark. `save_ci_reconciliation` atomically compares
that generation, saves only a projected REST snapshot with policy and evidence digests, and
advances the generation. Advancing it on successful saves prevents overlapping reconciliations
from replacing one another at the same watermark. A new webhook or competing save makes the
compare-and-swap fail. Historical webhook observations are never unioned into that snapshot.
Migration `0005` adds CI state/history; `0006` retains suite invalidation reasons.

Snapshots expire after 60 seconds. Reads parse timezone-aware timestamps and require
`reconciled_at <= now < expires_at` and a positive lifetime no longer than 60 seconds; malformed,
future-dated, expired or policy-mismatched snapshots cannot authorize readiness. Artifact digests
identify the retained reconciliation evidence. The API offers no way for a user to assert a
reconciliation or upload a trusted snapshot.

`GET /workflows/{id}/checks` authenticates and scopes repository access. `observed_ready` describes
provisional observations; `ci_ready` describes current generation/policy/time-bound provider checks.
Its `ready` field additionally requires the workflow to be at `HUMAN_REVIEW`, a current publication,
matching candidate/CI artifact context and configuration, and an unexpired applied plan approval
by a currently authorized reviewer. Failed, blocked, stale or revoked handoffs cannot advertise
ready merely because CI is green. Every response is explicitly observational, not a merge or
deployment authorization.

Two matching REST reads plus webhook generation checks reduce races but do not create a
transaction across GitHub and the local database. Provider eventual consistency, events not yet
delivered, or a change immediately after the final read remain possible. The 60-second cache is
a bounded read model, not a lock on GitHub. Required repository checks, protected workflow
definitions and human merge authority remain necessary. Real product-App onboarding and live
rerun/head-change tests remain an open release gate; owner-CLI discovery of repository/App IDs
or hosted CI results does not satisfy it.

## Official source verification

Checked 2026-09-28: the REST check-run schema includes IDs, `head_sha`, `name`, producing `app`,
status, conclusion and start/completion timestamps. Generic check runs do not provide the Actions
workflow-run `run_attempt` contract. A rerequest resets the suite but leaves the existing check
run unchanged until its producing App acts. The list endpoint supports filtering latest runs.
[GitHub check-run REST documentation](https://docs.github.com/en/rest/checks/runs?apiVersion=2026-03-10).

GitHub documents separate check-run and check-suite events, including `rerequested`; repository
webhooks do not receive every App-specific action. Configure App subscriptions/permissions and
retain reconciliation because webhook delivery alone is not a complete latest-attempt snapshot.
[GitHub webhook payload documentation](https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run)
(accessed 2026-09-28).

Contract tests exercise producer spoofing, stale heads, invalid IDs/timestamps, missing and
nonpassing checks, duplicate deliveries, conflicting updates, reruns, ordering, ambiguous latest
attempts, and attempts to label webhook input as reconciled. These tests use synthetic provider
fixtures; they do not constitute a live GitHub gate result.
