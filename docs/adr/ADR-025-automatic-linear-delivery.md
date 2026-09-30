# ADR-025: Owner-configured automatic Linear delivery

Accepted following the owner's explicit request on 2026-09-30 UTC: creating an eligible
Linear ticket should trigger execution and a reviewable PR without a separate plan click.

Repositories can opt into `automatic_execution`; the default remains false. For an
enrolled Linear ticket, the control plane records an idempotent `approve-plan` command
under `delivery-automation`. It evaluates the saved plan against current repository
configuration, original criteria, risk tiers 0/1, executable criteria and the existing
intake policy. Ambiguity, sensitive work and manual criteria require intervention.
The existing workflow consumes the command and retains its revision-bound approval.
Candidate, publication and handoff activities recheck current authority. Disabling
the setting invalidates automated authority. An automated decision is never recorded
as a human review. Builders still cannot approve plans, publish, obtain provider keys
or merge. Every merge remains human.

Use outbound Linear polling in the local runtime, following Agentic Product Ops'
bounded pagination, fixed enrollment date, overlapping cursor and idempotent intake
approach. The cursor advances only after a complete successful scan. Changed existing
ticket content is held without creating another run/budget. New unassigned eligible
issues are assigned to the configured worker; issues assigned elsewhere are skipped.
An explicit `Repository: name` must match the configured target. Existing signed
webhook intake remains supported; both routes converge on the same source identity.

This supersedes the requirement for a human plan approval on every run in ADR-006
only for opted-in eligible Linear work. Human merge control, finite per-run budgets,
isolated execution, independent review and current PR/check evidence remain required.
Polling needs the local service and machine online; it supplies no cloud uptime claim.
