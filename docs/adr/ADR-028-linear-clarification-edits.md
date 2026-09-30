# ADR-028: Resume paused clarification from Linear ticket edits

Status: accepted, 2026-09-30. Extends the opted-in Linear workflow in ADR-025.

An ambiguous ticket already pauses at NEEDS_CLARIFICATION. Previously the outbound
monitor held every content edit, so answering the question in Linear did not resume
the work. The operator had to separately issue an authenticated API command.

For an enrolled, assigned ticket whose latest workflow is NEEDS_CLARIFICATION, the
monitor may enqueue the existing `clarify` command under `linear-monitor` when the
title or description changes. The receipt binds the existing workflow sequence and
specification digest. It creates a specification revision in the same workflow and
retains its original budget, spending and attempt identity. Repeated polling creates
one command for the same revision. No new workflow protocol or migration is needed.

Before resolving this actor's command, the worker verifies current configuration,
automatic execution opt-in, source identity, paused state and command bindings. Only
title and description may differ. A fresh Linear read must match the configured
workspace, team, assignee, backlog/unstarted state and exact revised text. Provider
read failures remain retryable; revoked or stale source authority rejects the command.
Configuration is checked again after the read. The normal planner and risk policy run
again, and any build still needs a new eligible revision-bound plan approval.

This is source synchronization, not a fabricated human answer: the agent never invents
the missing decision. The user answers by editing the ticket. Changes during execution,
review or terminal states remain held. Additional questions can pause again within the
same finite budget. API clarification remains available. Source edits cannot remove
typed criteria, change repository/source identity, lower supplied risk, or grant tools.
