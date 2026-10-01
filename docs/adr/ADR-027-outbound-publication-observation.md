# ADR-027: Outbound publication outcome observation

Status: accepted, 2026-09-30; implemented and enabled in the local service (see the
[live record](../live-automatic-delivery.md#outbound-publication-observation-follow-up)).
Extends the local outbound operation in ADR-025.

The local delivery service can detect tickets and finish CI without a public webhook.
After handoff, however, signed GitHub callbacks were its only way to observe changed,
closed or merged PRs. That left publication records stale in the installed local mode.

Add an optional `github-monitor` service, enabled with `github_poll_enabled`. It reads
only persisted publication identities for onboarded repositories. Each request uses
a short-lived GitHub App token restricted to that numeric repository and Pull requests
read permission, then revokes the token. The endpoint is fixed; provider links never
select a request destination. GitHub documents this permission and response in
[Get a pull request](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request).

Validate and persist only PR identity, state, timestamp and head/base metadata. Use
the existing publication observation reducer and an explicitly separate `github-rest`
receipt provenance; REST reads are never represented as signed webhook deliveries.
Repeated metadata deduplicates durably. Older provider timestamps cannot supersede
newer observations. Changed revisions retain the existing STALE/MERGED_UNVERIFIED
semantics. Reopening a stale or closed PR does not restore verified readiness.

Poll bounded pages in stable workflow-ID order and rotate the cursor across cycles.
An individual unavailable PR cannot starve the rest of the page. Restarting begins
the scan again safely. Configuration is checked before reads and again before storing
observations. The setting is operational: it does not change execution digests or
grant candidate, publishing, merge, model-spending or Linear-write authority.

This is separate delivery-status observation. A merge does not change the completed
workflow into a deployment success, and it does not update Linear to Done. Required
CI checks still use the existing independent readiness broker before handoff. Live
signed callback validation and a real human merge remain separate qualification cases.
