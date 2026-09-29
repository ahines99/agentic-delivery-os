# Lossless semantic file-pool codec

`evaluation.semantic_file_pool` is a pure, unconnected codec. It performs no artifact
read/write, model call, forecast, calibration, execution or authority validation.
Existing semantic contexts, prompts, grants, receipts and full-context model inputs
are unchanged. No production consumer selects this profile yet.

```python
packed = encode_semantic_file_pool(original_context)
restored = decode_semantic_file_pool(packed)
assert restored == original_context
```

The explicit `lossless-file-pool-v1` envelope stores each distinct file-content string
once, keyed by SHA-256 of its exact UTF-8 bytes. Three manifests map every original
path to that key, separately for `source_files`, `candidate_files` and `oracle_files`.
All other context fields remain present and unchanged, including purpose, context ID,
original artifact references, diff, normalized execution evidence, rubric and digests.
Empty files, leading whitespace, Unicode and CRLF are preserved without normalization.
Identical content at different paths or roles shares storage without merging identity.

The envelope binds the original `digest_json(context.model_dump(mode="json"))`.
Decoding rejects missing/extra roles, unsafe paths, missing or unused blobs, invalid
UTF-8, incorrect content hashes, duplicate JSON keys at any depth, nonfinite values,
unexpected fields, changed purpose, inconsistent evidence/candidate digests and
normalizing/coercing inputs. It reconstructs the typed context and requires its exact
canonical re-encoding to reproduce the original envelope bytes. Input encoding is
deliberately canonical: sorted JSON keys, standard spaced separators, ASCII escapes,
UTF-8, no final newline. Alternate equivalent JSON spellings are refused.

The existing 512 KiB full-context JSON limit remains in force. Before rebuilding file
maps, the decoder computes expanded size using metadata plus each referenced string's
encoded length; many references to a large shared string cannot bypass this bound.
Envelope input is limited to 1 MiB, with existing per-file/path/count checks and bounded
JSON-tree processing. Pooling can increase small inputs because hashes and manifests
add overhead. No fit, cost saving, corpus coverage or model-accuracy claim follows.

Round-trip validity is only structural consistency. The original digest is a binding,
not an authenticated approval: an artifact writer could author an entirely different,
self-consistent context. A future consumer must compare against its trusted original
context/digest and independently reconstruct current qualification, data-use, runtime
and rubric authority. This codec reads none of those underlying artifacts. The tests'
historical-shaped inputs are original toys with explicitly synthetic reference fields,
not historical admission or executed scoring evidence.

## Required before any model use

A separate, explicit calibrated prompt/profile must explain manifest-to-content lookup.
Output citations must continue to name original source/candidate/oracle artifact IDs,
paths and file-line coordinates; pool keys are transport identifiers, not citation
artifact substitutes. Expected answers and reference closures remain excluded by the
original protected context authority; the codec does not scan or authorize content.

Actual broker request/context digests must bind the envelope sent to the model, while
an immutable plan separately binds the original context digest. Readback must reconstruct
both representations and their authority. Forecast the actual serialized request with
the existing algorithm and unchanged caps. Old full-context operations must remain
readable and must never be relabeled, migrated or retried under a packed profile.
This slice supplies none of that integration or authorization.

Owned tests cover both purpose variants, exact content/metadata preservation, shared
paths, canonical encoding, corruption/ambiguity refusal, expansion refusal before
typed-context construction, and exact size boundaries. They need no provider, Docker,
historical data or credentials.
