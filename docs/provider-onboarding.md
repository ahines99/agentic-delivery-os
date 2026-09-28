# Live provider onboarding

The implementation PR is maintained with the owner's authenticated GitHub CLI. The product
publisher accepts only a GitHub App installation; CLI credentials are never a fallback.
Keep `publication_enabled=false` until the following inputs and checks are complete.

## GitHub App

1. Open this [prefilled private App registration](https://github.com/settings/apps/new?name=ahines99-agentic-delivery-os&url=https%3A%2F%2Fgithub.com%2Fahines99%2Fagentic-delivery-os&public=false&request_oauth_on_install=false&webhook_active=false&contents=write&pull_requests=write).
   Choose a unique name if needed. The only requested repository write permissions are
   Contents and Pull requests. Metadata is implicit. No organization, administration,
   Actions, workflow-file, or user OAuth permissions are needed by this publisher.
2. Register the App, generate its private key, and install it on **only** the approved target
   repository. Keep the PEM in an owner-readable ignored file. Set the worker's
   `GITHUB_APP_PRIVATE_KEY` environment variable to its contents, without printing it.
3. Set `github_app_id`, `github_installation_id`, and the repository's numeric
   `github_repository_id` in private configuration. These are distinct identifiers.
4. For observations, configure an HTTPS callback ending in `/webhooks/github`, subscribe to
   pull-request events, and set a fresh webhook secret both in GitHub and the API process's
   `GITHUB_WEBHOOK_SECRET`. Never put a secret in a URL. Keep other API routes private.
5. Protect the target base branch with required independent checks and human review. Grant
   the App no bypass. The publisher has no merge operation; installation write permission
   is still sensitive and must not be mistaken for a provider-enforced "draft-only" permission.
6. Enable publication only for a new explicitly approved attempt. Material configuration
   changes invalidate existing attempts. Exercise one draft PR, lost-response reconciliation,
   changed-head/base rejection, and signed close/merge observations before recording a live gate pass.

The registration URL preselects settings; it does not register or install an App.
GitHub documents [registration URL parameters](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-using-url-parameters)
and [permission selection](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app).

## Linear

Configure one workspace organization ID, one team per repository, a worker assignee ID and
a review-state ID. Record these as `linear_organization_id`, `linear_team_id`,
`linear_assignee_id`, and `linear_review_state_id`. Supply an authorized personal API key as
`LINEAR_API_KEY` for this single-tenant prototype. A production OAuth lifecycle remains separate work.

A workspace admin must configure an Issue webhook for that team pointing to a publicly
reachable HTTPS `/webhooks/linear` endpoint. Put its signing secret in the API process's
`LINEAR_WEBHOOK_SECRET`. The route verifies exact raw-body signatures, timestamps, workspace,
team and assignee, then commits the inbox/outbox receipt before returning. Linear's
[webhook documentation](https://linear.app/developers/webhooks) describes the admin and HTTPS requirements.

Test a clear ticket, ambiguity/clarification, duplicate delivery, changed requirements,
assignment changes and review-state handoff. A changed payload for the same ticket is a
conflict requiring explicit revision handling; it does not silently fork a fresh budget.
Do not expose Temporal, PostgreSQL, the Docker daemon, or operator credentials through a tunnel.

## Evidence required before closing the gate

Retain the real provider resource IDs, revision tuple, workflow/command IDs, manifest digest,
actual model usage and signed notification dispositions. A local synthetic run or mock HTTP
transport is not this evidence. Provider credentials should be supplied by local file path or
the worker's environment, never pasted into an issue, PR, ticket or model context.

The project repository's `main` branch currently requires all four CI checks, up-to-date
branches, one approving review, resolved conversations and linear history; administrator
enforcement is enabled, force pushes/deletions and automatic merge are disabled. These settings
protect this project. Each subsequently onboarded target needs its own verification.
