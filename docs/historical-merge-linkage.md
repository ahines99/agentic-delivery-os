# Explicit first-parent merge linkage

`HistoricalMergeLinkageEvidenceV2` supports one additional provider-reported profile:
a complete accepted two-parent merge commit whose first parent is the exact acquired
baseline. The second parent is retained as metadata, never selected as an alternate
baseline. This does not broaden reference derivation or documentation-change support.

The opt-in producer is `freeze_historical_merge_linkage(...)`; its arguments match the
existing linkage producer. It consumes two matching trusted-caller metadata captures,
uses the unchanged fixed `LINKAGE_QUERY`, and writes protected immutable artifacts only
after validation. It makes no network request, reads no credential and executes no
repository code. Its independent schema-2 kind is
`provider-reported-first-parent-merge-linkage-v2`, with an explicit
`FIRST_PARENT_BASELINE_TWO_PARENTS` profile and ordered `accepted_parents` tuple.

Validation requires exactly two complete parent nodes, no pagination, distinct valid
nonzero 40-hex commit identifiers, no accepted-commit self-parent, and first-parent
equality to the reconstructed baseline acquisition. Both captures must match entirely.
Repository numeric/node identity, exact accepted commit/tree, merged PR and unique
matching issue closer, requirements capture, full B/A acquisition and derivation
reconstruction remain mandatory. Existing chronology is unchanged: requirements
precede accepted commit time, which is no later than PR merge; closure and all captures
must obey the existing ordering and current-time bounds.

`validate_historical_merge_linkage(...)` reads only this explicit complete schema.
`validate_historical_linkage_record(...)` dispatches solely on the exact schema/kind
pair and refuses unknown, missing or relabeled identities. Import, preparation and
derived-rights validation use this dispatch; qualification-input resolution reaches it
through the shared preparation validator. Both the exact new linkage digest and
provider capture enter the computed model-exclusion closure. Sibling artifacts of the
new container kind are also rejected as supporting review text or rubric.

The existing `HistoricalLinkageEvidence`, `LINKAGE_QUERY`,
`freeze_historical_linkage(...)`, and `validate_historical_linkage(...)` remain
unchanged. They continue to mean single-parent linkage, with the old serialized bytes
and two-parent refusal. There is no automatic record migration, parent fallback or
reinterpretation. An existing data grant cannot be reused by merely substituting a
new linkage digest: parent/derived authorization binding and both current trusted
policy pins remain required. Merge metadata does not grant rights, execution, model
spending, import acceptance or task admission.

This remains a provider-reported assertion under the trusted caller's fixed-origin
capture boundary, not cryptographic authentication of Git history. The ordered parent
connection is taken as that provider's assertion. Accepted-commit/merge chronology
does not prove the issue text predates every earlier branch implementation or public
solution disclosure. Current rights, protected review, full qualification and family
checks remain separate gates. No actual historical candidate is qualified by this
module or its owned tests.

`tests/test_historical_merge_linkage.py` covers the complete owned two-parent path,
parent order/identity/count/pagination faults, changed captures and cross-record
bindings, strict dispatch and relabeling, no partial writes, read-only reconstruction,
current import/preparation/resolver rights and expiry gates, reference exclusion, and
legacy schema/query/public-function golden checks. All provider responses and source
fixtures in these tests are original owned synthetic data; no live acquisition or
historical execution is part of this change.
