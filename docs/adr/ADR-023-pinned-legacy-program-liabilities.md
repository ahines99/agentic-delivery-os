# ADR-023: Pin archived liabilities into a new versioned program budget

Status: implemented with owned verification; live inventory and program release gates remain open.

## Decision

Extend [ADR-020](ADR-020-prospective-program-budget-envelopes.md) with an explicitly selected
schema-2 policy. Before registry creation, the trusted controller captures the exact collection
of [archived legacy ledgers](ADR-022-legacy-ledger-archival.md) under current metadata permission.
Each row retains target identity, archive authorization and nonce, stable accounting digest,
all account IDs including zero-cost accounts, settled cost and unresolved reservation liability.
The collection is sorted, duplicate targets/account IDs are refused, and every concrete archived
store is read twice. A caller-supplied total or parsed inventory is never sufficient for creation.

`ProgramBudgetPolicyV2` pins both the exact historical target list and inventory digest, alongside
the full program cap and distinct prospective targets. `ProgramBudgetRegistry.create` requires
the corresponding concrete context, reconstructs and matches it, then checks it again before
committing registry creation. Schema-1 policy bytes and registries remain unchanged; supplying
historical context to a schema-1 policy is an error. Existing registry files are never upgraded
or replaced implicitly.

Every schema-2 registry transaction validates the stored inventory against the policy digest.
Available capacity is the full cap minus archived settled/reserved liability and current held
or closed prospective envelopes. Unknown historical charges are never released. Account IDs
from archived ledgers cannot be recreated as fresh prospective accounts. Tampered/missing
inventory fails closed; there is no API to reduce or delete historical liability.

## Current reporting

Current program reconciliation requires the original concrete legacy context for a schema-2
registry, rederives its accounting, and matches the pinned inventory before and after prospective
ledger reconstruction. Missing current permission or changed archive facts cannot become a
successful report. Campaign reporting checks legacy permission outside its unavailable-evidence
fallback, so revoked permission denies the requested report.

Schema-2 program reports expose legacy settled and reserved amounts separately from existing
prospective `observed_totals`. Do not add legacy amounts a second time to registry capacity:
the registry already includes them. `historical_costs_included=true` means exactly the declared,
concretely verified archived selection. It does not attest that every program ledger was declared.

## Remaining requirements

This does not authorize live archival, renew execution/data grants, reconcile provider invoices,
prove older writers stopped, attest complete program inventory or make unresolved cost known.
`complete_program_cost` and execution/promotion authority remain false. Historical source,
oracle and model payloads are not read by these APIs. No live historical ledger has been archived
or imported during implementation. Future finite execution must use an authorized inventory and
current permissions; old registries/grants cannot be relabeled with this policy.
