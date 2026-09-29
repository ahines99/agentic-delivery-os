# Exact final-scorer prompt versions

`semantic_calibration.semantic_prompt(rubric)` remains the original v1 function and
produces exactly the original bytes. No stored spec, grant, context, output schema or
receipt is migrated. Existing v1 records still reconstruct their original prompt,
request digest, reservation and settled accounting.

New preparation may explicitly choose:

```python
prompt = semantic_prompt_for_version(rubric, version="v3")
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
the artifact equals the exact generated v1, v2 or v3 bytes. It does not normalize the
artifact, trust a version label inside it, decode and repair malformed bytes, or
accept trailing whitespace or altered guidance. Rubric canonicalization remains the
same existing `strip()` behavior in every version.

Both calibration readback/execution and the two-initial-scorer executor use this same
resolver against their pinned prompt artifact. The existing spec and grant schemas
have no added version field or default. The prompt artifact digest remains the exact
version binding, and the real broker receipt still binds the prompt, context, schema,
configuration, request and measured usage. A larger prompt changes its forecast
reservation naturally through the existing shared serialization; no ceiling is
increased by the resolver.

A different prompt version needs a separately authorized calibration spec, plan and
account. An already started or completed account cannot be rebound from v1 to v2/v3
or from v2 to v3, even with an updated allowlist. The original record and all costs
remain immutable. Historical semantic execution still requires current successful calibration for its exact pinned
prompt and model; adding a prompt version itself confers no authority or success.

Tests pin original v1 prompt/schema digests, exercise completed v1 readback without
new calls, validate v2 controlled broker receipts and exact executor wire bytes,
reject modified or unknown artifacts, and deny reuse of a completed v1 account under
v2. Out-of-range lines and missing acceptance-node citations still fail validation
and retain their observed charges. Scripted HTTP responses establish machinery,
not improved live model accuracy. No paid calibration is part of this change.

V3 appends only a generic independent-finding assessment protocol to the exact v2
bytes. It directs the scorer to judge each criterion against its own stated predicate,
input domain and execution conditions, without propagating another finding's failure
or a global verdict. A demonstrated violation is `FAIL`; insufficient necessary
requirements/evidence is `UNRESOLVED`; evidence supporting that predicate within its
scope is `PASS`. Integrity findings are assessed separately. One defect can affect
multiple findings only with evidence for each effect. The overall verdict is computed
last using the unchanged existing precedence. This does not equate passing tests with
coverage, change citation requirements, or modify any expected finding or validator.
The appended guidance is independent of the rubric's content and contains no fixture
or case-specific directions.

This is prospective grading clarity, not a diagnosis of a prior aggregate mismatch or
a prediction that calibration will pass. No private model output or historical
artifact informed the implementation. A v3 calibration failure must retain its
original evidence and costs under the same failure rules as earlier versions.

The expanded tests pin v2's original bytes as well as v1's, exercise exact v3 broker
wire/receipt/forecast and executor bindings, and deny completed v1/v2 account reuse
under v3. Existing invalid-citation cases remain invalid and charged. The owned
fixture contexts, expected decisions, serialized spec/grant schemas and output
validators remain unchanged.

Related: [executed owned calibration](semantic-calibration.md),
[initial semantic execution](semantic-execution.md), and
[citation contracts](semantic-scoring-context.md).
