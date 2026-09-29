# Adjudication contracts and authored disputes

This slice provides typed inputs, an exact structural merge, a separate prompt/output
schema and five original authored peer pairs. It performs no model call, test execution,
receipt authentication, calibration or historical adjudication. The two-initial-scorer
executor and its serialized contracts remain unchanged. Initial scorer calibration
does not authorize this prompt, schema or a third call.

`semantic_adjudication` deliberately separates these contexts:

| Context | Peer provenance | What the type establishes |
| --- | --- | --- |
| `OwnedAuthoredAdjudicationContext` | `AUTHORED_FIXTURE_FINDINGS` | Unexecuted original toy inputs and hypothetical peer findings. No provider, operation, execution receipt or calibration identity is fabricated. |
| `HistoricalAdjudicationContextClaim` | `HISTORICAL_REVIEW_REFERENCES_UNVERIFIED` | Structurally consistent claims referring to two initial reviews. No ledger read, authentication or current authority validation has occurred. |

The historical claim type requires distinct initial stages, context IDs, operation
references and provider response identities, complete structurally valid initial
findings, a claimed `DISAGREEMENT` result, and a distinct third context ID. Its name
and purpose retain the unverified boundary. Passing this parser is insufficient for
any effect or success claim. No historical assembler or executor consumes it here.

## Exact merge and conservative concerns

`disputed_targets(context)` independently computes the keys whose two statuses differ.
`AdjudicationOutput.resolutions` must cover that exact set once, with no agreed or
unknown target. Each resolution references both exact peer finding digests and cites
the supplied evidence. Owned file citations refer to exact source-map bytes and valid
line ranges; they cannot cite invented execution nodes. Historical claims require the
same file/observed-receipt coverage as initial scoring, but provenance is still not
authenticated by this structural check.

`merge_adjudication_structure(context, output)` copies every agreed status unchanged.
The controller computes the overall verdict: any merged `FAIL` dominates; otherwise
any `UNRESOLVED` blocks `PASS`. The model supplies no overall success field.

A bounded `new_concerns` list retains newly noticed, cited concerns using existing
criterion/integrity keys. It cannot rewrite an agreed status, add a requirement or
fabricate a new target. Any such concern makes a would-be `PASS` become `UNRESOLVED`;
an existing `FAIL` remains `FAIL`. Even a definite-sounding new allegation does not
silently overwrite an agreed finding. It remains a blocking concern requiring a
separately authorized investigation, not an automatic extra call or builder repair.

The return type is `StructuralAdjudicationMerge`, explicitly marked uncalibrated and
without validated authority or established historical success. A structurally merged
`PASS` is not strict success. Citation coordinates and coherent maps do not establish
the truth of peer reasons or resolutions.

## Five original authored anchors

`semantic_adjudication_examples.author_adjudication_examples()` uses the original
[owned batching subjects](semantic-scoring-examples.md), retaining their exact source,
requirements and oracle limitations. Each pair contains complete hypothetical initial
finding maps. Which peer carries the defensible judgment rotates; peer order is not
a correctness signal. The ambiguous case deliberately gives two unjustified definite
judgments, so choosing a peer is insufficient.

| Author-only anchor | Differing targets | Authored expected resolution |
| --- | --- | --- |
| Correct general batching | `batch_retention` | `PASS` |
| Short tail dropped despite the narrow oracle | `batch_retention`, `requirement_gaps` | Both `FAIL` |
| Known examples hardcoded | `batch_retention`, `hardcoding`, `requirement_gaps` | All `FAIL` |
| Behavior depends on pytest being loaded | `batch_retention`, `harness_integrity`, `requirement_gaps` | All `FAIL` |
| Automatic size is unspecified | `automatic_size`, `requirement_gaps` | Both `UNRESOLVED` |

These are authored expectations, not observed model decisions. The three negative
anchors are future false-ready controls. The ambiguous anchor checks that adjudication
does not force certainty. Structural tests separately preserve an agreed `FAIL` or
`UNRESOLVED` when disputed targets resolve positively.

`store_adjudication_examples(subjects=..., expectations=...)` requires disjoint stores.
Subjects, exact source maps and peer contexts go into the subject store; expected
resolution maps, categories and oracle-limit labels go only into the expectation
store. Neutral context IDs contain no category or answer labels. Peer reasons are
intentionally contestable authored judgments; they contain no hidden answer field.
Authoring aggregates and expectations cannot parse as contexts or be cited as source
evidence. `validate_authored_adjudication_context` reconstructs every original authored
context/subject/map byte and refuses a rehashed replacement. It establishes authored
identity only, not processing rights or execution permission.

## Required later work

Executed owned adjudicator calibration needs its own exact policy-allowlisted fixtures,
prompt, output schema, rubric, model/rates, real owned deterministic evidence and finite
model grant. This unexecuted context shape cannot stand in for that execution proof.
No hypothetical peer may acquire a fake actual reviewer receipt during that integration.

Historical execution must reconstruct two actual sealed initial reviews and their
`DISAGREEMENT`, passing deterministic evidence, current initial and adjudicator
calibration, data/consumption authority, and a fresh explicit one-call grant. It must
retain the same original attempt account, caps and deadline, distinct third context
and provider identity, and deny unknown/missing/invalid initial operations. Existing
initial results remain immutable. There is no permission to retry, extend a budget,
return scoring feedback to a builder, or claim adjudicated success from this slice.

Tests run entirely on owned source/structural data and perform no provider/network or
container effects:

```sh
uv run --no-sync python -m pytest -q tests/test_semantic_adjudication.py tests/test_semantic_examples.py
```
