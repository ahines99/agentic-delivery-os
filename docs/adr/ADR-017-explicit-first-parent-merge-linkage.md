# ADR-017: Explicit first-parent merge linkage

Status: accepted and implemented, 2026-09-29; historical use remains unverified.

## Context

The historical linkage reader supports only single-parent accepted commits. That is
an implementation restriction, not a release requirement that upstream use squash
merges. Metadata-only screening found small repositories with issue-linked two-parent
merges. Their source, oracle suitability, runtime, rights and full derivation eligibility
remain unverified. Supporting their commit shape does not admit them.

## Decision

Add an explicit `HistoricalMergeLinkageEvidenceV2`, distinct schema/kind and
`FIRST_PARENT_BASELINE_TWO_PARENTS` profile, retaining the ordered two parent SHAs.
Separate merge freezer/validator entry points require exactly two complete, distinct,
valid, non-self parent identities. The first parent must equal the complete acquired
baseline. The second parent is metadata, never an alternative baseline.

Retain two matching fixed-origin provider captures, exact acquired accepted tree,
repository identity, merged PR, matching issue close event and all existing requirement,
commit, merge and capture chronology checks. The current query already requests two
parents; truncated or inconsistent connections remain invalid. Provider assertions do
not become cryptographic commit authentication or proof of earliest solution disclosure.

Preserve existing v1 classes, default functions, serialized bytes and single-parent-only
meaning. Add a shared reader that selects only by exact schema/kind, with no fallback
or numeric inference. Update current import, preparation, derived authorization and
qualification consumers to reconstruct the selected contract. New linkage identities
need their own exact rights/data-use bindings; old records and grants remain unchanged.

## Verification and limits

Use owned fixtures to verify the complete merge path and current consumers; reject
reversed, duplicate, self, invalid, missing, extra or truncated parents; reject relabeled
v1/v2 documents and changed PR/issue/tree/chronology. Pin v1 serialization and denial
behavior. No network, historical payload, execution or spending authority follows from
this design or a structurally valid record.

All ADR-013 reference-derivation restrictions remain unchanged, including rejection of
non-Python changes, controls, licenses, dependencies, new paths and unsupported test
selectors. A proposed separate documentation disposition has not been accepted or
implemented by this ADR. The corpus minimum, qualification matrix, independent review,
split isolation and promotion gates are unchanged.

The [implementation](../historical-merge-linkage.md) passed 144 affected owned tests
in the author worktree. Independent review passed 77 linkage cases, and root integration
passed 121 merge/linkage/import/derived-input cases. These scopes overlap and contain no
live historical acquisition or admission.
