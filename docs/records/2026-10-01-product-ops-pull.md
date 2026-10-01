# 2026-10-01: Product Ops pull intake (DO-3)

## What changed

- **Ported from #9 (slim).**
  - The vendored Product Ops contract: verifier, schema, documentation capability model and
    the CommonMark read-back.
  - `integrations/product_ops.py` (`admit`), `ProductOpsTrust` and `Settings.product_ops`.
  - Admission tests and the synthetic fixture.
  - The narrow gitleaks allowlist for its test digests.
  - ADR-035.
- **Left out of #9.**
  - The push endpoint.
  - The documentation execution lane, plus its dispatcher and CLI changes.
  - The wheel smoke script.
- **New.**
  - `integrations/product_ops_client.py`: the `Handoff:` parser and read-only retrieval.
  - The pull path in the Linear monitor, sharing a `claim` helper with normal intake.
  - `admit` accepting the system pull actor.
  - Store inbox lookups.
  - DO-4 reporting for Product Ops runs.
  - [ADR-038](../adr/ADR-038-product-ops-pull-intake.md).

## Verification

- `tests/test_product_ops_client.py`: 20 passed. Covers reference parsing, the configured host
  and token, every response class, oversize, redirect, plain HTTP outside the local host, and
  digest exclusion.
- `tests/test_product_ops_pull.py`: 13 passed. Covers:
  - admission before claim, with no normal intake;
  - holding on `404`, stopping on `410`, and never claiming a refused envelope;
  - admitted work claimed without refetching;
  - holding a busy repository before any fetch;
  - malformed references, a missing pickup contract, and unconfigured retrieval.
  - One end-to-end test runs the real verifier and `admit` on a re-signed synthetic envelope
    whose ticket carries the contract lines. It shows one fetch, one admission and a claim,
    and no second admission on a re-poll.
- `tests/test_product_ops.py`, `tests/test_product_ops_markdown.py` (from #9): pass.
- **Contract update (2026-10-01).** `linear_markdown.py` is re-vendored from Product Ops `main`
  `a154945` (SHA-256 `3c73101b…`, the PER-16 entity-decoding fix) and the pin in `UPSTREAM.md`
  is updated. The other three files match that commit.
  - New tests show that entity-decoded `<`, `>`, `&` and apostrophes still match, and that
    changed text is still refused.
  - Run against the old copy, the apostrophe case already matched. The `<`/`>` cases failed:
    Linear's decoded `<tag>` parses as raw HTML. That is the regression this update fixes.
- **Confirmed by Product Ops.** The `Repository:` and `Handoff:` lines are written at plan time,
  inside the signed plan's description and digest. Nothing is added after signing.
- `tests/test_linear_progress.py`: 13 passed, including a Product Ops run reported on its
  published ticket.

## Not verified

Not installed in the local service, and not exercised against the live Product Ops endpoint or
Linear.

## Installation settings

Under `product_ops`:

- `issuer`: `product-ops-local`
- `key_id`: `pilot-v1`
- `public_key_hex`: `a3200b5735b1ecc03ce1ceff8e19a5f8573e1a5bd06a086a83dfb52e6d58e5fa`, the
  hex form of the shared base64 key `oyALVzWx7MA84c7/jhml+Fc+GlvQaghqg9+1Lm1Y5fo=`
- `handoff_base_url`: `http://127.0.0.1:18013`
- `workspace`: `product-ops-pilot`
- `teams`: `["21daab21-ad28-4aa3-8e03-2aedc00f2e40"]` (the shared `product` team)
- `policy_versions`: `["pilot-execution-v2"]`

Product Ops hands off risk tiers 0 and 1 only. Product Ops checked the computed key hex
against the base64 signing key and confirmed it.

The service's environment must set `HANDOFF_READER_TOKEN` from the owner-held reader token.
