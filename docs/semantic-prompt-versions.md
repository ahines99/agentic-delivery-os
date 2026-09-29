# Exact final-scorer prompt versions

`semantic_calibration.semantic_prompt(rubric)` remains the original v1 function and
produces exactly the original bytes. No stored spec, grant, context, output schema or
receipt is migrated. Existing v1 records still reconstruct their original prompt,
request digest, reservation and settled accounting.

New preparation may explicitly choose:

```python
prompt = semantic_prompt_for_version(rubric, version="v2")
prompt_artifact = protected_artifacts.put(prompt.encode())
```

The version argument is required. There is no `latest`, automatic upgrade or unknown
version fallback. V2 retains the original instructions and adds generic citation
construction guidance. It asks the scorer to count decoded file lines, verify small
in-range spans, copy exact artifact/path identifiers, copy an observed acceptance
node from the matching execution receipt, and check every finding's required citation
list. Concise reasons distinguish evidence from coverage limits. The guidance applies
equally to `PASS`, `FAIL` and `UNRESOLVED`; it contains no fixture labels or expected
decisions. Structural validators and semantic expectations are unchanged.

`resolve_semantic_prompt(rubric, artifact_bytes)` returns `(version, prompt)` only when
the artifact equals the exact generated v1 or v2 bytes. It does not normalize the
artifact, trust a version label inside it, decode and repair malformed bytes, or
accept trailing whitespace or altered guidance. Rubric canonicalization remains the
same existing `strip()` behavior in both generators.

Both calibration readback/execution and the two-initial-scorer executor use this same
resolver against their pinned prompt artifact. The existing spec and grant schemas
have no added version field or default. The prompt artifact digest remains the exact
version binding, and the real broker receipt still binds the prompt, context, schema,
configuration, request and measured usage. V2's larger request changes its forecast
reservation naturally through the existing shared serialization; no ceiling is
increased by the resolver.

A fresh v2 prompt needs a separately authorized calibration spec, plan and account.
An already started or completed v1 account cannot be rebound to v2, even with an
updated allowlist. The original record and all costs remain immutable. Historical
semantic execution still requires current successful calibration for its exact pinned
prompt and model; adding the v2 function itself confers no authority or success.

Tests pin original v1 prompt/schema digests, exercise completed v1 readback without
new calls, validate v2 controlled broker receipts and exact executor wire bytes,
reject modified or unknown artifacts, and deny reuse of a completed v1 account under
v2. Out-of-range lines and missing acceptance-node citations still fail validation
and retain their observed charges. Scripted HTTP responses establish machinery,
not improved live model accuracy. No paid calibration is part of this change.

Related: [executed owned calibration](semantic-calibration.md),
[initial semantic execution](semantic-execution.md), and
[citation contracts](semantic-scoring-context.md).
