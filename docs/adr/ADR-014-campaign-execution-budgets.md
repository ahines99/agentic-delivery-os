# ADR-014: Separate qualification and campaign execution budgets

Status: accepted for the explicit schema-3 campaign contract, 2026-09-28.
Execution-controller integration remains pending. This decision authorizes no spending.

## Context

The evaluation methodology meters preparation and qualification separately from each
equal-cap arm attempt, while including both in the overall campaign cost. A qualified
task's immutable manifest currently contains the budget used during qualification.
Real development qualification needed a larger review allowance than the protocol's
per-attempt comparison limits and used no repair rounds. Schema-2 campaign freezing
requires those budgets to be identical, preventing an already admitted task from
participating under the separate comparison limits.

Editing an admitted manifest would break its evidence bindings. Treating a larger
qualification allowance as permission for larger arm spending would invalidate the
comparison. Resetting budgets for each stage would also give review or scoring
unreported extra resources.

## Decision

Keep existing task manifests, qualification records and schema-2 freeze behavior
unchanged. Add an explicit `freeze_execution_campaign` API and schema-3
`ExecutionCampaign`. It retains the exact admitted task digest and qualification
artifact and declares that execution limits come from the frozen arm configurations.
It also declares that builder, review, repairs and final scoring share those limits.
No offline CLI automatically upgrades or executes this schema.

The existing protocol ceilings, arm parity, complete corpus, family/split separation,
current calibration and qualification authority, seeded schedule and worst-case
campaign cap all still apply. Preparation remains a separate, explicit reservation
inside the overall campaign cap. Freezing produces metadata only: it creates no
execution account, spending grant, worker export or result.

The eventual controller must bind a separate finite execution authorization to the
exact campaign, ordinal, arm configuration, original admitted manifest and current
policy. One ledger account per arm attempt will share model, token and infrastructure
limits across generation, review and all final scoring. Scoring cannot create extra
capacity or send protected feedback back into the builder. A changed candidate
requires newly bound evidence; qualification budgets are never silently substituted
for execution limits. Existing schema-1 scoring authorization remains unchanged. The explicit schema-2
[scoring consumer](../campaign-scoring.md) implements this separation using an already
allocated, checkpointed attempt account and current trusted controller authorization.

The builder-only arm must make no independent-review call; it cannot fabricate an
approval to reuse product readiness. Product delivery retains independent review and
human plan/merge controls. Post-candidate semantic scoring needs its own calibrated
prompt/schema and independent passes. Qualification calibration and deterministic
passing tests alone do not establish strict benchmark success.

## Consequences and verification

Schema 3 can freeze equal-cap execution specifications without changing admitted
bytes. Legacy schema 2 still refuses unequal task/arm budgets and cannot parse the
new record as its own. Owned contract tests cover these distinctions, current
authority revocation, retained task identities, cap/parity/corpus failures and
deterministic output. Their injected authority boundary is not a real qualified
corpus or a completed campaign.

Actual campaign execution still requires the controller, independent semantic-scoring
calibration and complete qualified corpus. Until those
exist, the new record remains `PREREGISTERED_NOT_EXECUTED` with spending unauthorized.
