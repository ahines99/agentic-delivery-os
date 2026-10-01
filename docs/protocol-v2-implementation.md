# Explicit campaign protocol dispatch

Implements the prospective contract in
[ADR-016](adr/ADR-016-prospective-campaign-token-ceilings.md).

Protocol `agentic-historical-v2` is an additive contract for prospective schema-3
execution campaigns. It permits at most 500,000 shared input tokens and 64,000
shared output tokens per attempt. The model ceiling remains $5, infrastructure
ceiling $1, active deadline 1,800 seconds, and campaign ceiling $1,000. All builder,
review, repair, final scoring and adjudication usage shares the existing attempt
account. A new protocol tag does not allocate another account or restart its clock.

`CampaignSpecificationV2` requires the explicit protocol literal. Its arms use
`ArmConfigurationV2` (schema 2 plus the same protocol literal), and trusted current
policies use `CampaignAllocationPolicyV2` and `CampaignExecutionPolicyV2` (schema 2
plus the protocol literal). The common resolvers select contracts by these tags
and refuse mixed versions. They do not infer a version from numerical limits or
retry parsing under a more permissive contract.

The original `AttemptLimits`, `ArmConfiguration`, `CampaignSpecification`,
allocation/execution policy classes and `Budget` remain unchanged. Their v1
100,000-input/20,000-output ceilings are still enforced. Existing default JSON
and public contract schemas have golden regression coverage. Legacy campaign
freezing and CLI schema defaults remain v1. Only `ExecutionCampaign`'s schema-3
specification union accepts either explicitly tagged protocol; existing v1
artifact fields and serialized values remain unchanged.

Allocation, A/B candidate execution, deterministic scoring, semantic execution,
and both candidate/scoring consumption readers resolve the exact frozen protocol.
Current qualification, calibration, data-use and policy checks remain in place.
Historical task and qualification bytes are not rewritten to obtain execution
capacity. Previously sealed grants and accounts are not upgraded.

At the example frozen rates of $5 per million input tokens and $25 per million
output tokens, the v2 token maxima cost $4.10. This is a feasibility calculation,
not a substituted reserve: the broker still reserves from complete serialized
request bytes plus its existing allowance and the frozen model prices. Different
prices or repeated large contexts may exhaust the $5 ceiling earlier. Freeze
still budgets the full $6 per attempt plus the explicit preparation reservation,
and still enforces the complete corpus, repository separation, stability subset
and identical arm limits. The 512-KiB full-context cap and supported context
profile are unchanged; no truncation, context selection or token-estimate API was
introduced.

Owned tests exercise canonical allocation, A and B candidates, both read-only
consumers and deterministic scoring on one original account/deadline. Separate
controlled-provider tests exercise two final semantic scorers on their existing
account. Qualification/calibration and sandbox results in these tests are owned
controlled fixtures; they do not demonstrate an actual historical campaign or
a new end-to-end orchestrator. A larger owned source context demonstrates that
the explicit v2 reservation can fit where v1 refuses, without changing its bytes.
Mutation tests cover mixed/unknown/missing tags, caps and corpus/parity gates.

Production orchestration and finite grants remain separate work. This change
neither executes a campaign nor promotes any attempt or semantic result.
