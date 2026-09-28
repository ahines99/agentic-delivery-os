# Protected historical reference derivation

`evaluation.historical_derivation` implements the first offline producer from
[ADR-013](adr/ADR-013-derived-historical-reference.md). It is not wired into
historical import, preparation, qualification, worker export or scoring. A record has
`DERIVED_NOT_IMPORTED`, `NOT_AUTHORIZED`, `admitted=false` and
`execution_authorized=false`; none grants rights or spending authority.

```python
record_artifact = derive_historical_reference(
    ReferenceDerivationRequest(
        baseline_acquisition_artifact=baseline_capture_artifact,
        accepted_acquisition_artifact=accepted_capture_artifact,
        protected_paths=("private_package",),
    ),
    protected_artifacts=protected_store,
    worker_roots=(checkout_root, worker_root),
)
record = validate_reference_derivation(
    record_artifact,
    protected_artifacts=protected_store,
    worker_roots=(checkout_root, worker_root),
)
```

Only the protected evaluator may inspect returned record metadata, paths or selectors.
The producer returns a digest, never raw source. Both acquired full text snapshots and
Git inventories remain unchanged. Each is revalidated using content-addressed reads,
complete Git tree reconstruction, per-path size/SHA-256 and recomputed Git blob hashes.
The repositories and numeric identities must match, and commits must differ. This does
not establish commit ancestry, accepted-fix linkage, chronology, requirements relevance,
licenses or current data rights; versioned import still needs those separate bindings.

The profile permits only modifications to existing Python implementation and existing
conventional Python test files. Every changed file is partitioned, with original and
accepted content hashes. Added, deleted or renamed paths, changed file/directory modes,
control files, licenses and non-Python changes refuse the entire derivation. Supplied
protected paths add to built-in restrictions. At least one production and one test
change are required. All original baseline tests and controls remain unchanged.

Production target text is taken exactly from the accepted tree. Deterministic unified
patches are applied again with the existing strict parser and must reconstruct exactly
that production-only change. The initial patch profile requires LF and a final newline
in changed production files; it never normalizes unsupported bytes.

Each complete accepted test file is copied unchanged to
`__evaluation_oracle__/test_<sha256-original-path>.py`. Both complete original and
accepted file contents have protected artifact references. Imports, helpers, classes,
fixtures, line endings and assertions are retained, without selecting helper definitions
or rewriting source. The original path and relocated path are explicitly different.
Any existing use of the oracle namespace refuses the derivation.

Acceptance selectors include every added or AST-changed supported direct `test_*`
function or direct `test_*` method of `unittest.TestCase` / directly imported `TestCase`.
AST comparisons include full function signatures, decorators and bodies, without line
number differences. Duplicate or removed tests, decorators on tests/test classes,
async tests, unsupported class bases, conditional/nested test definitions, module markers,
late-bound test assignments and recognized collection hooks refuse the profile. This
static profile is not a proof of Python execution behavior. Unchanged tests are retained
in the copied file but are not acceptance selectors. No selector is removed in response
to an observed execution result. Syntax is parsed only; no code is imported or executed.

A relocated test may fail to import or collect, particularly with relative imports or
repository fixtures. Future integration must freeze explicit original regression paths
excluding `__evaluation_oracle__`, use these exact acceptance selectors, and run the
existing twelve-operation matrix. Every frozen acceptance node must call-fail on the
baseline and pass on the reference; original regressions must remain stable and pass.
This producer constructs no command or execution grant and has not run that matrix.

The executable baseline is original baseline plus oracle. The executable reference is
original baseline plus exact production patch plus oracle, intentionally different from
the complete accepted tree. Validation reconstructs all artifacts and the entire record
without writes; altered dispositions, selectors, paths or source bindings fail closed.
Errors contain one constant message. All validation and size checks precede writes;
an I/O failure can leave unreferenced protected artifacts but cannot return success.
Protected storage must be disjoint from every nonempty caller-declared worker/code scope.

## Required subsequent integration

Preserve existing `ReferenceProvenance` and historical import v1 serialization. Introduce
an explicit versioned provenance/import branch requiring this reconstructed derivation;
never label its executable reference as the accepted upstream tree. Bind the task's
source/oracle/reference/patch, acceptance selectors, complete source inventory, issue,
accepted commit and acquisition timestamps through that branch and current preparation.

The model-evidence exclusion closure must include the accepted snapshot and its capture
and inventory, production patch, executable reference, derivation and any provenance or
import aggregate that embeds accepted implementation. Existing reference exclusions alone
are insufficient. Only the separately authorized oracle is eligible for protected review;
worker export stays baseline-only. Shared contracts and exclusions are deliberately
unchanged in this standalone step, so this record is not consumable as legacy provenance.

Validation uses owned synthetic Git trees and HTTP fixtures. No historical payload,
model call, Docker execution, task import, benchmark qualification or admission was used
or claimed in implementing this producer.

## Subsequent protected development observations

After implementation and independent review, a protected attempt for the previously
acquired `tkem/cachetools` PR 408 candidate refused the conventional test-filename
predicate. That attempt and its sanitized implementation-location diagnostic remain
retained. No derived oracle or reference was produced, and the profile was not changed
to admit it.

A metadata-only screen of the latest twelve previously observed, single-parent,
issue-linked replacement PRs outside that repository found ten unsupported deltas
and two potentially compatible deltas. It requested Git trees only, not source,
issue bodies, patches or test answers. All outcomes remain retained; this convenience
screen is not a representative sample or a qualified dataset.

The first metadata-eligible lead, `dbader/schedule` PR 463 (issue 175), was then
acquired into protected storage: all 29 baseline files, totaling 122,503 bytes, and
the complete accepted tree. Thirty-seven unauthenticated requests transferred
292,568 bytes. Derivation and independent reconstruction succeeded with two changed
files, one whole accepted test file relocated, and two frozen acceptance selectors.
The resulting record is `DERIVED_NOT_IMPORTED` and `NOT_AUTHORIZED`. No historical
source, test identity, issue text or accepted implementation was exposed to the
interactive implementation context. No historical code or model ran.

Separate protected issue acquisition reported no edits, with requirements as of
2017-11-09 preceding the PR's recorded 2022-04-10 merge. This remains provider-reported
chronology, not archival proof. The root license matched SPDX MIT grant, conditions
and disclaimer after whitespace normalization, with its notice retained; heuristic
notice checks are not all-file rights clearance. Current processing authorization,
accepted-fix linkage, runtime qualification and independent semantic reviews remain
required. Neither replacement has been imported, qualified or added to the campaign.
