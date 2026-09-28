# ADR-013: Explicit historical reference derivation

Date: 2026-09-28. Status: source-layout execution and standalone protected derivation
implemented; versioned import integration remains in progress. Historical runtime
qualification remains pending. This decision does not admit a replacement candidate.

## Problem

The existing importer preserves every original test and control file. An accepted
upstream fix can change both implementation and an existing test, so its full Git
diff cannot satisfy that rule. Dropping the test change while claiming an exact
accepted tree would give false provenance. Separately, the current trusted collector
supports flat imports; a source-layout repository needs explicit execution support.

## Decision

Keep five distinct, immutable identities in protected storage:

| Identity | Meaning |
| --- | --- |
| Baseline | Exact complete acquired pre-fix repository, including original tests and controls. |
| Accepted tree | Exact complete acquired accepted commit, including all test changes. |
| Production patch | Deterministic eligible implementation differences, with target bytes taken exactly from the accepted tree. |
| Oracle | Separately frozen test files and selectors, with explicit derivation provenance. |
| Executable reference | Baseline plus production patch plus oracle; explicitly different from the accepted tree. |

Introduce an opt-in versioned derivation/import record. Preserve existing v1 record
serialization and proof meanings. Validate the complete baseline-to-accepted
difference: every changed path and mode receives a disposition. The initial profile
accepts modifications to existing eligible Python implementation files and existing
conventional Python test files. Controls, licenses, dependency changes, renames,
unsupported modes and other changes refuse this profile. No unclassified omission
or selection of only convenient production changes is allowed.

Retain both complete versions of every changed test. The initial oracle route copies
each complete accepted test file byte-for-byte to a deterministic, disjoint evaluator
filename. The record binds its original path, relocated path and exact content digest;
it does not call the relocated file an unchanged upstream path. Original baseline
tests remain unchanged in both executable variants. No assertion rewriting, helper
selection or installation hook is part of this derivation.

Freeze supported changed/added direct test functions or unittest methods as acceptance
selectors before observing execution results. Do not remove a selector afterward
because it already passes on the baseline. Dynamic or parameterized node identities
need a separately specified collection procedure and remain unsupported initially.
Relocation can break relative imports or fixtures; actual collection/runtime failure
rejects the task. Existing regression discovery must exclude the oracle namespace.

The existing twelve-run qualification matrix remains mandatory: every frozen
acceptance node must call-fail on the baseline and pass on the reference, with stable
passing original regressions. Setup errors, collection errors, skips and model claims
do not substitute. Independent protected reviewers still assess requirement relevance,
test adequacy, risk, rights, linkage and family grouping.

The full accepted tree, production patch and derivation artifacts containing accepted
implementation stay excluded from model supporting documents and worker exports.
Only the explicitly authorized oracle remains visible to protected qualification
reviewers under [ADR-010](ADR-010-executable-qualification-stages.md). Interactive
implementation agents and campaign builders/reviewers retain their existing exclusion.

## Source-layout execution

Extend the trusted command grammar with only the exact optional pair
`-o pythonpath=src`. Bind it through existing command/configuration digests and a newly
pinned collector image. The collector interprets this directive itself; it does not
enable arbitrary pytest overrides, repository config, conftest, environment paths,
package installation or setup hooks. Reject repeated directives, missing/unsafe roots
and target-package collisions that could test an image-installed package instead of
the supplied source. Trusted image modules load before repository import paths.

Keep the report/profile version when its protocol is unchanged: the immutable image
and exact argv already distinguish new semantics. Existing commands and their hashes
remain unchanged. A new field with a default on every command would unnecessarily
invalidate old evidence. Tasks using the new image/directive require fresh runtime
evidence; completed unrelated operations and accounting are not rewritten.

## Required validation and limits

Use owned synthetic tests for exact derivation/partition reconstruction, unchanged
original tests, relocated-byte/selector bindings, invalid changes, sanitized errors,
reference exclusion and old serialization compatibility. Actual Docker checks must
prove source import origin, baseline acceptance failures, reference success, original
regressions and unchanged flat-layout behavior. Host and collector grammar must agree.

After implementation and review, a protected producer may inspect actual accepted
bytes and report only eligibility metadata to implementation context. The observed
candidate's metadata does not prove that its changed nodes, dependencies or import
behavior fit this profile. No historical outcome, rights decision, qualified task or
campaign follows from accepting this design alone.
