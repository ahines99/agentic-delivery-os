# Bounded source-layout verification

The image-owned collector accepts the exact optional argv pair `-o pythonpath=src`
once in an operator-configured `python -m pytest` command. This implements the
source-layout portion of [ADR-013](adr/ADR-013-derived-historical-reference.md).
It does not acquire, derive, qualify or score historical tasks.

The collector consumes the directive itself. It does not forward an arbitrary pytest
override or load repository pytest configuration, conftest, environment import paths,
installation hooks or `.pth` files. Existing command serialization, collector report
version 1 and `image-owned-pytest-v1` profile remain unchanged. The pinned image digest
and exact argv identify the added capability in existing receipt bindings.

Before adding any repository import path, the collector verifies that `/workspace/src`
is a real directory with no symlink descendants. It inspects top-level Python modules
and package/namespace directories without importing them. Empty or ambiguous module
sets, names already loaded by the interpreter, standard-library/builtin names, image
imports and same-named workspace-root imports are refused. Every initial source
resolution must point inside the supplied src tree. The collector then appends src
and workspace after trusted image paths; it does not prepend source over installed
dependencies. This deliberately conservative profile can reject repositories with
otherwise intentional namespace or installed-package overlap.

Delivery criterion invocations preserve this directive only from validated operator
profiles. All configured verification commands must agree on whether they use src;
mixed profiles fail before runner/model construction. Builder-supplied test selectors
cannot introduce options. Manifest admission independently checks that each criterion
receipt uses the configured import profile, even if a changed receipt and all its
digests are recomputed. Existing flat-layout criterion argv remains unchanged.

The checks establish initial import resolution. Test/application code still executes
in the collector interpreter and could manipulate imports or pytest later; this is
not attestation against arbitrary hostile Python. Existing sandbox, provenance,
independent-oracle and human-review boundaries continue to apply.

## Owned verification

`tests/test_src_verification.py` checks host/collector grammar parity, unsupported
override rejection, stable command serialization, missing/unsafe roots, installed
and root import collisions, and nonexecution during origin inspection. Actual Docker
cases exercise src/flat package origins, opt-in behavior, collisions and a Linux
symlink. A four-run owned fixture demonstrates a baseline acceptance call failure,
reference success and unchanged passing original regressions. It is a profile
regression test, not the historical twelve-run qualification matrix.

The actual pipeline test in `tests/test_evidence_manifest.py` uses controlled model
fixtures and real Docker verification for both layouts, including independently
executed criterion commands and full manifest revalidation. It makes no provider
call or claim of live model quality.

Set `TEST_SRC_SANDBOX_IMAGE` to the newly built immutable src-capable image to run the
new Docker cases. `TEST_SANDBOX_IMAGE` continues to select the ordinary existing
integration image; neither variable alters repository settings or old evidence.

```sh
python -m pytest tests/test_src_verification.py tests/test_verification.py tests/test_pipeline.py tests/test_evidence_manifest.py
```

Changing a task to the new image/directive requires fresh bound execution evidence.
The implementation does not rewrite completed unrelated qualification records,
configuration artifacts or settled accounting.
