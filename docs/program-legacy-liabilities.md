# Include archived liabilities in a program registry

[ADR-023](adr/ADR-023-pinned-legacy-program-liabilities.md) adds an explicit schema-2 policy
for new registries with historical liability. The original schema-1 policy remains prospective.

1. Stop older writers/workloads and complete the separately authorized
   [legacy archival](legacy-accounting.md) procedure for each exact historical target.
2. Construct `ProgramLegacyContext` with concrete archived stores and a current permission
   guard covering their complete sorted identity list. Capture the inventory with
   `capture_program_legacy_inventory(context=...)`. It reads each actual store twice, retaining
   every account and unknown reservation without reading model result payloads.
3. Construct `ProgramBudgetPolicyV2` with the approved full cap, prospective target identities,
   exact sorted historical identities, and captured `legacy_inventory_digest`. The two target
   collections must be disjoint. Duplicate historical account IDs are refused.
4. Create a new registry with `legacy_context=...`. Creation rederives the concrete inventory,
   matches the policy, and checks it again before commit. Merely supplying serialized reports
   or a number cannot reserve historical liability. An existing registry is never overwritten.
5. Enroll new empty prospective ledgers normally. Their account envelopes compete with all
   retained archived costs/reservations. Reopening the registry preserves those liabilities;
   unknown historical charges cannot disappear when a new account closes.
6. Supply the same concrete legacy context to `ProgramAccountingContext` for current reports.
   A changed archive or missing permission refuses reconstruction. The report keeps historical
   settled/reserved amounts separate from prospective usage and retained future capacity.

For example, an owned inventory with 14 settled and 60 reserved microdollars consumes 74 of a
174-microdollar cap before any prospective account exists. A new 100-microdollar envelope uses
the remaining capacity. Closing that new account at 10 microdollars releases only 90; all 74
historical microdollars remain included. This is a test example, not a project spending result.

Full inventory attestation, live archival, provider invoice reconciliation, current execution
authorization and promotion remain separate. These APIs have only been exercised with owned
test data. `historical_costs_included` describes the exact declared archived selection, not a
claim that unlisted ledgers or external invoices are covered.

## Verification

The final legacy/archive/store/registry/accounting scope passed 179 tests in 50.85 seconds with
actual PostgreSQL and no skips. Eight campaign-reporting cases passed in 20.63 seconds,
covering the prior prospective reader and new concrete historical selection, revoked legacy
permission and changed archive facts. Earlier 54- and 65-test scopes each had one unconfigured
PostgreSQL skip; an earlier 179-test run preceded the final report schema assertion. These
overlapping scopes are not summed. Unique owned databases were dropped and absence verified.
Lint/format (381 files), mypy (119 sources) and source/wheel builds passed. Exact-head full CI,
independent review and authorized live inventory remain required.
