# ADR-032: bounded workflow recovery of an existing publication

Status: accepted for implementation; installation and verification are tracked in
[implementation status](../implementation-status.md).

## Problem

A publishing process can die after GitHub accepts a draft PR but before the activity
records its result. The existing broker can reconcile an explicitly repeated call,
but the workflow previously ended on the failed publication activity. Automatically
repeating all publication writes would also allow an uncertain surviving worker to
race another creator.

## Decision

New workflows heartbeat publication once per second with a twenty-second heartbeat
timeout. Publication still has one attempt and a five-minute start-to-close limit.
On activity failure or timeout, the workflow performs one separately named
`recover_publication` activity with the same operation identity and manifest. A
cancelled activity or accepted cancellation command does not enter recovery.

Recovery revalidates current configuration, approval, manifest bindings and, for a
Linear ticket, current issue identity, assignment and text. The publisher's
`existing_only` mode requires an existing branch and exactly one matching PR before
proceeding. It checks the expected tree, commit marker, current base, numeric repository
identity, exact PR head/base, draft/open state and final authoritative PR response.
Incomplete or malformed listings cannot establish recovery.

This mode cannot create commits, branches or PRs, or change existing refs or PRs.
It uses GitHub's content-addressed `POST /git/trees` to reconstruct the expected tree,
so it is **not read-only** and retains the repository-scoped contents/PR write token.
Current authorization gates that operation; token revocation remains cleanup.
No builder receives these credentials. A disappearing branch or PR is not recreated.

A confirmed publication is persisted and proceeds through the existing manual
acceptance, exact-head CI and tracker handoff gates. An unconfirmed result records
`UNKNOWN` and terminates at `POLICY_BLOCKED`. A digest-addressed recovery receipt
binds workflow, manifest, observation time and outcome; exception messages are
excluded. If confirmation occurred before a subsequent authorization failure, the
observed publication remains stored, but the workflow cannot declare readiness.
Failure of the recovery activity itself follows the existing workflow failure path.
Recovery never reruns the builder or independent reviewer.

The `publication-recovery-v1` Temporal patch preserves commands of older recorded
histories. Production worker registration includes both activity names. This is a
workflow change, not a database migration or a change to merge authority.

## Limits and verification

A crash after branch creation but before a confirmed PR remains blocked for explicit
reconciliation. We do not create a missing PR while a prior worker's effects are
uncertain. This does not fence a partitioned surviving process, recover lost host
storage, guarantee vendor-side cancellation or prove provider outages.

The owned regression exercises real PostgreSQL and Temporal, actual abrupt worker
process exits and a replacement worker using the production publisher and recovery
activities. Candidate receipts, HTTP provider effects and CI responses are controlled
fixtures; they are not historical or live delivery evidence. Provider mutation guards,
authority changes, cancellation, immutable receipts and saved histories also have
focused tests. Recorded results belong in the capability record, not this decision.
