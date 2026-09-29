# Anthropic fixed-tuple generation schema

The Anthropic request adapter projects only homogeneous fixed tuples into its
array `items` representation. For example, Pydantic emits the adjudication output's
`peer_findings` as two identical `prefixItems` references with exact min/max length
two. The provider-facing projection uses one `items` reference plus the description
`Must contain exactly 2 items.` The original output contract is unchanged.

[Anthropic's structured-output documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
describes a simplified generation schema followed by validation against the original
schema. Its [official Python SDK transformer](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/lib/_parse/_transform.py)
handles arrays through `items` and limited `minItems`, treating unhandled properties
as unsupported description material. Inspection of the public application schema
showed the previous adapter forwarded `prefixItems` without `items`; removing only
min/max constraints did not address that compatibility gap. These primary sources
were checked on 2026-09-29. The local controlled tests do not establish live provider
acceptance or successful adjudication calibration.

The projection requires a nonempty list of identical original item schemas and
integer `minItems == maxItems == len(prefixItems)`. Equality is checked before
constraint stripping, so two different constrained types cannot accidentally become
an accepted homogeneous tuple. Mixed prefix item types, malformed/empty prefix lists, unknown lengths,
conflicting tail schemas, or extra tuple semantics such as `contains` and
`unevaluatedItems` are refused. An absent tail or explicit `items: false` is supported.
Nested homogeneous fixed tuples are handled recursively. Errors contain no schema
values. The pure forecast rejects unsupported tuples; the broker rejects them before
budget reservation and HTTP. This is not a general positional-tuple converter.

The provider projection is generation guidance, not a relaxation of accepted output.
The original Pydantic model still checks exact length and item types after response
parsing. Invalid output retains the existing uncertain reservation and cannot cause
an automatic replacement call. There is no provider retry or financial reconciliation
change. The original schema digest, prompt and expected judgments remain unchanged;
the normalized provider body has a new request digest and forecast where the tuple
projection changes it. Previously frozen tuple requests are not silently migrated.

Non-tuple schemas retain their existing wire representation and reservation basis.
OpenAI's schema path is unchanged. Golden checks captured before this change cover
actual controlled Anthropic wire bytes, request digests, spaced serialization sizes,
reservations, settled receipts and cached no-reissue behavior for implementation
planning and initial semantic scoring. Thus an unrelated initial-calibration request
is not changed by the new tuple projection.

`tests/test_anthropic_tuple_schema.py` uses only original owned schema/payload fixtures,
`httpx.MockTransport`, and the real model adapter/ledger. No historical inputs, private
provider responses, credentials or paid calls are used. The structured adjudication
payload in these tests is a schema fixture, not a calibrated reviewer decision or
historical execution authority.
