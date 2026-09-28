# Deliberately failing delivery baselines

`tests/test_baseline_failure.py` exercises the actual `build_and_review` pipeline,
Docker isolation preflight and image-owned pytest collector against two original,
synthetic snapshots. It supplies a test plan directly; it does not invoke a planner,
claim human approval, import historical data or contact a model provider.

The assertion fixture contains one passing existing test and one failing existing
test. The second fixture raises during collection. Both must return `FAILED` with
`Baseline verification failed`, a failed baseline summary and its actual execution
receipt. Neither may produce a candidate, repair attempt, review or readiness manifest.
The model's generation entry point is a test sentinel: any builder, reviewer or other
generation call fails the test. A real SQLite control store must contain zero model
reservations. The production model object is constructed but never invoked.

The checks inspect collected test identities, phase outcomes, collection failures,
pytest exit codes, snapshot/command bindings and the pinned image. The mixed assertion
fixture demonstrates that an existing failed test remains visible alongside a passing
one. It is not misreported as a candidate regression: no candidate has been built.
Both actual container IDs must be absent after completion; cleanup checks never remove
or enumerate unrelated workloads for deletion.

The baseline receipt is retained by the production verifier. Each test additionally
retains its actual preflight receipt, snapshot and pipeline failure as content-addressed
artifacts, with a metadata-only `baseline-failure-evidence.json` in its pytest directory.
No generated artifacts are committed.

## Recorded local check

On 2026-09-28, the focused integration run passed **2 tests in 6.64 seconds** using
image `sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8`.
It created and removed four containers: a preflight and baseline for each fixture.
The retained baseline receipt digests are:

- Assertion failure: `918867673a849bdc44c66b96bff85ecdfc8c8ba427decd03eee1885e4291898a`.
- Collection failure: `a94ddecb74f317c7d67f8afaf321023f1137f72152a161d5f5096ea4d83a7160`.

Local evidence is under the isolated worktree's ignored `.local/bf-c8f50312/`;
each case has its own artifact store and metadata index. The first test invocation
failed during pytest setup because the evidence parent directory did not exist;
it performed no Docker/model work. The recorded successful invocation followed
creation of that parent and used a fresh evidence directory.

To repeat, set `TEST_SANDBOX_IMAGE` to an available immutable collector image and run
`python -m pytest tests/test_baseline_failure.py -q`. Without the variable, integration
tests explicitly skip. Use a new, nonexistent `--basetemp` directory beneath an existing
private parent when evidence must remain separate from routine pytest retention.

## Product-gate boundary

This closes the missing deliberately failing **local baseline** evidence for P-11
and part of M2-02. The explicit failure is suitable for operator triage; the production
workflow routes a non-ready candidate result to `FAILED` with its reason and evidence.
This particular drill does not run Temporal or prove a human received, understood or
resolved that failure. End-to-end human-triage routing and broader dependency/runtime
qualification remain open. The same-interpreter collector limitations also remain;
this is an owned failure fixture, not hostile-code isolation qualification.
