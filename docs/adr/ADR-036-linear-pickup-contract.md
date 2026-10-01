# ADR-036: Linear pickup contract, version 1

Status: accepted, 2026-10-01; implemented in the Linear monitor (roadmap items DO-1 and DO-2).
Not yet installed in the local service.

## Problem

On 2026-09-30 Product Ops published PER-16 and PER-17 into the shared Linear team. The
Linear monitor claimed both within minutes. It took any unassigned Backlog or Todo ticket in
the team that did not name a different repository, and it treated a missing `Repository:`
line as consent. The policy blocked both runs, so nothing was built, but two systems that
share a team must agree on which tickets one of them may take.

## Decision

The monitor applies the joint roadmap's pickup contract version 1 before it claims a ticket
or applies a clarification edit:

- **Repository line (DO-2).** The description must contain a `Repository:` line. Every such
  line must name this repository: its configured id, its GitHub name, or an entry in
  `linear_repository_names`. A ticket with no line, or one that also names another
  repository, is skipped.
- **Opt-in label (DO-1).** The ticket must carry the repository's `linear_pickup_label`, which
  defaults to `delivery-ready`. Setting it to `null` disables the label requirement for that
  repository; the repository line stays mandatory.
- **Checked on the fresh read.** Both checks run against the version read immediately
  before claiming, not only the scan result.

The label is a routing signal, not authority. It grants nothing: eligibility, risk policy,
budgets, plan approval and human merge are unchanged. Verifying Product Ops' signed approval
for a labelled ticket is roadmap item DO-3, which needs its own decision.

`linear_pickup_label` and `linear_repository_names` affect intake routing only. They are
excluded from the execution digest, so changing them never invalidates an in-flight run.
The digest of an existing configuration is unchanged by this ADR.

## Consequences

- A ticket without the label is never assigned or run, which reproduces the PER-16 case.
- Tickets created by hand, such as PER-13 and PER-14, now need the label as well as the line.
  The runbook, README and automatic-delivery guide say so.
- The contract names the target by repository directory name. This repository's directory
  name (`agentic-delivery-engineer`) differs from its GitHub name (`agentic-delivery-os`), so
  either Product Ops writes the GitHub name or the owner adds the directory name to
  `linear_repository_names`.
- Removing the label before a claim stops pickup. After a claim, cancellation follows
  roadmap item DO-6.
