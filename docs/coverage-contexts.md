# Revision-bound coverage hints

`agentic_delivery.repository.coverage` imports offline measured line contexts and ranks
test identities by overlap with changed base-source lines. It is not wired into the
product build/verification pipeline. Every ranking has `full_suite_required=True`;
neither a ranked test nor an empty list authorizes narrowing the approved suite.

Coverage.py's [`json --show-contexts` option](https://coverage.readthedocs.io/en/latest/commands/cmd_json.html)
includes line contexts. [Measurement contexts](https://coverage.readthedocs.io/en/7.12.0/contexts.html)
can be static, dynamic, or combined labels. Initial execution may have an empty dynamic
context. A context label is therefore not inherently a test identity. This importer
requires an explicit receipt-bound mapping from full context labels to test node IDs;
it never guesses by splitting labels on pipes or importing test modules.

## Artifacts and API

Store both UTF-8 JSON artifacts in an existing content-addressed directory with layout
`ROOT/<first-two-digest-characters>/<sha256>`:

- Source snapshot: an object mapping safe repository-relative POSIX paths to text. The
  receipt binds the digest of these exact JSON bytes, not only an informal Git revision.
- Coverage JSON: the exact exported report bytes. Formats 2 and 3 are supported;
  unsupported fields/formats fail closed. The extractor uses file-level executed,
  missing and excluded lines plus contexts. It does not derive branch coverage or
  function/class-region statistics from ignored summary fields. The format-3 structure
  follows the [coverage.py JSON reporter](https://github.com/nedbat/coveragepy/blob/7.12.0/coverage/jsonreport.py).

`MeasurementBinding` requires repository identity, full base SHA, source artifact digest,
image digest, toolchain digest, command/configuration digest, context-mapping digest,
coverage version, and fixed extractor `coverage-json-contexts-v1`. Command/configuration
provenance must cover both measurement and export options (including context/include/omit
filters), environment, dependency lock, and instrumentation configuration. Callers decide
and freeze their canonical configuration documents; this module cannot infer them from
coverage JSON. Use `storage.store.digest_json(context_tests)` for the mapping digest.

```python
from agentic_delivery.repository.coverage import import_coverage, rank_tests

coverage_map = import_coverage(
    artifact_root,
    receipt,
    expected=expected_binding,
    context_tests={"tests.test_calc.test_one": "tests/test_calc.py::test_one"},
)
ranking = rank_tests(
    coverage_map,
    {"package/calc.py": (12, 13), "package/other.py": None},
    expected=expected_binding,
)
```

`CoverageReceipt(binding=..., report_artifact=...)` binds report bytes. Both APIs require
an independently supplied expected binding; any changed repository, base, snapshot,
image, toolchain, command, context mapping or version raises before returning a ranking.
Do not derive `expected_binding` from an untrusted receipt in production. Full context
labels are mapped exactly, and mapped test-file paths must exist in the bound snapshot.
Test node IDs are opaque metadata, never executable commands.

`rank_tests` accepts safe changed-file paths mapped to **base snapshot line numbers**,
or `None` for the whole file. New/deleted/shifted candidate lines require a separately
validated diff-to-base mapping; never reuse candidate coordinates as base coordinates.
An absent file is unknown. Suggestions sort by descending distinct covered changed-line
count, then test ID; each includes touched files. This is an ordering hint for earlier
feedback, not proof that a test will detect a regression.

## Explicit uncertainty and trust boundary

Unmeasured files/lines, empty files, unexecuted statements, missing context exports,
empty contexts, and unmapped contexts produce explicit unknown records. Empty reports
mark snapshot files unmeasured. Empty source snapshots, unsafe paths, out-of-range
measurement lines, duplicate JSON keys/lines, contradictory states, mismatched tool
versions, modified artifacts and stale bindings fail closed. An empty test ranking
never means there is no impact. Unknown labels are not copied into output; only mapped
test identities and categorized reasons are retained.

The standalone reader performs no writes and rejects links/junctions, nonregular files,
path escapes, digest mismatches and reads over 8 MiB. It parses bounded JSON only; it does
not deserialize `.coverage` databases, execute imports, run repository code, or contact
providers. POSIX opens use nonblocking mode before checking the descriptor's regular-file
type, so a FIFO cannot stall the reader waiting for a writer. A subprocess regression test
has a ten-second deadline; it explicitly skips on Windows, which lacks POSIX `mkfifo`.
The artifact directory and its ancestors must be controlled by the local
operator: path checks are not a hostile concurrent-filesystem isolation boundary.

Receipts remain **caller-supplied measurement claims; hashes are not attestation**.
They establish consistent bytes and claimed provenance, not that coverage was honestly
collected, the configured image executed, the declared suite completed, or the context
mapping is correct. Candidate code and coverage instrumentation can lie. Production
integration still needs an authenticated trusted measurement producer, isolated execution,
collection/completion checks and receipt verification. Stale contexts cannot establish
current candidate coverage; all mandatory verification remains independently required.

## Validation boundary

The unit suite uses clearly synthetic reports. An optional test actually measures a tiny
disposable synthetic program with an already installed coverage.py interpreter, exports
`--show-contexts`, imports it and ranks the executing test. Select the interpreter with
`COVERAGE_TEST_PYTHON`; otherwise the test uses the project interpreter and skips when
coverage.py is absent. It installs no dependencies. The initial local run used existing
global Python 3.14 with coverage.py 7.15.0; fixture image/configuration identifiers in that
test are synthetic claims, not evidence of a pinned-container execution. No historical
repository, task, campaign result, or integration with the live pipeline is implied.
