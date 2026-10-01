# ADR-029: Preserve test packages during historical derivation

Date: 2026-09-30. Status: implemented; qualification remains a separate gate.

The first markdownify development execution stopped before collection because the
whole-file relocation profile broke a relative import of an unchanged sibling helper.
Keep that failed attempt, its original selectors and settled accounting. Fix the
general import-layout limitation using owned fixtures before any fresh historical run.

Add the explicit `PackageReferenceDerivationRequest` (schema 2) and
`existing-python-test-package-v2` record. Existing schema-1 request/record fields,
serialization and derivation behavior remain unchanged. Content validators dispatch
on the explicit version and reconstruct the full artifact graph; a profile label
alone does not establish provenance or authorize execution.

The controller declares complete top-level `tests` or `test` directories before
execution. Each declared directory must contain only eligible Python files, without
runner/control overrides or protected paths. Copy every file under those directories
to the same relative layout beneath `__evaluation_oracle__`. Preserve exact baseline
support bytes, then replace only the complete changed test files with their exact
accepted bytes. No helper subset, import rewriting, generated package initializer or
production solution is added. Unsupported data files or controls reject this profile;
they are not silently omitted. Absolute imports, dynamic imports and fixtures can
still require unsupported behavior, which actual qualification must detect.

Every upstream change retains the existing complete disposition rules. Changed
helpers, dependency/control changes, removed tests and unsupported test identities
remain refused. Acceptance selectors still name all changed/added supported nodes;
original baseline tests remain unchanged in both executable variants. Package support
files are bound by the exact oracle digest and reconstructed baseline inventory.
Current protected-path checks cover their original locations as well as relocated
paths, including when policy tightens after derivation.

The existing v2 import, data authorizations, current-use authority and qualification
controller accept the new reconstructed record without a new execution workflow.
New derivations require fresh linkage/data bindings and execution evidence; old
failures or approvals do not become successful by changing a version field.
The twelve-run matrix, independent calibrated reviews, reference exclusion, finite
budgets and human merge boundary are unchanged. No historical admission follows
from this implementation or its owned tests.
