# Executed owned adjudication contexts

`OwnedAdjudicationContextAuthority` in `evaluation/semantic_owned_adjudication.py`
binds the five [authored peer pairs](semantic-adjudication-contracts.md) to current
[owned runtime evidence](owned-semantic-context.md). It executes no code or model,
creates no budget account or grant, and establishes no calibration or historical
scoring authority.

The frozen constructor requires the concrete `OwnedSemanticContextAuthority`,
original authored artifact store and context digest, a fresh `context_id`, and the
exact approved rubric digest. `assemble()` revalidates the original pair and
current runtime, prepares only idempotent subject-derived projections using the
existing owned adapter, and returns `ExecutedOwnedAdjudicationContext`.
`validate(context)` reconstructs everything read-only; it cannot repair missing
artifacts. Both paths check current runtime/receipt and rubric authority again
before returning. The authored store must be disjoint from the worker root.

The new purpose is `OWNED_EXECUTED_ADJUDICATION_CALIBRATION`. Underlying execution
evidence retains its truthful `OWNED_DEVELOPMENT_CALIBRATION` purpose and
`baseline_executed=False`: only the candidate acceptance/regression work was run.
The initial scorer contracts and the original unexecuted authored contexts remain
unchanged. The two peer judgments retain exact original authored bytes and
`AUTHORED_FIXTURE_FINDINGS` provenance. They acquire no fabricated provider response,
operation, or reviewer receipt identifiers. No expected decisions, category labels,
or diagnostic artifacts enter the assembled context.

Original authored subject JSON and existing runtime subject JSON use different
serializations. The adapter validates both exact content-addressed artifacts,
requires equality of the complete strictly parsed `SemanticSubject`, and separately
compares every source/candidate/oracle byte map, map digest, requirement, criterion,
and authorship field. It retains the original authored-context digest and actual
runtime subject digest instead of asserting equal hashes for differently encoded
JSON. A changed hypothetical peer or a rehashed authoring bundle is refused.

`merge_adjudication_structure` accepts the new context type while remaining a
structural check, never an authenticated/calibrated model judgment. Hypothetical
peers retain file-only citations. New resolutions and concerns must cite the
actual owned evidence: criteria and requirement gaps include an observed acceptance
receipt/node, harness integrity includes baseline plus both execution receipts,
and hardcoding includes baseline and oracle. File paths and line ranges are
validated with the unchanged initial scorer citation checks. Only independently
computed disputed targets may be resolved; agreed statuses remain fixed and new
concerns block a would-be PASS. Every merge still reports
`authority_validated=False`, `calibrated=False`, and
`historical_success_established=False`.

The adapter alone does not freeze a paid adjudication prompt/schema or create a
calibration grant. Any future executed adjudicator needs a separately reviewed
prompt and independently successful adjudication calibration; initial-scorer
calibration grants no such authority. Historical adjudication additionally needs
authenticated actual peer operations, which this authored-pair adapter never
supplies.

`tests/test_semantic_owned_adjudication.py` covers all five original pairs using
controlled owned collector responses and the actual evaluation ledger. These
controlled responses are test doubles, not real container evidence. The optional
`TEST_SANDBOX_IMAGE` test runs a real owned candidate through Docker before context
assembly. Tests also reject peer/subject/context/rubric/receipt tampering, expired
or revoked runtime policy, missing projections, expectation/aggregate aliases,
worker-exposed storage, and fabricated node/line citations; read-only validation
is tested with all writes and runner construction forbidden. No provider requests
or historical artifacts are used.


The scoped implementation check passed 35 tests, including one actual Docker owned
candidate context using pinned image
`sha256:174b3ce4e50a09a7b2e2ce2ce41af429353236841fa356c76bae7b009c572716`.
The remaining fixture runtime cases used the explicitly controlled collector. This
is context/receipt compatibility evidence, not an adjudicator model or calibration
result. Independent review found no remaining blocker in this bounded adapter.
