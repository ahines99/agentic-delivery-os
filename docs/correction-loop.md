# Controlled correction-loop evidence

The owned cases in [`tests/test_correction_loop.py`](../tests/test_correction_loop.py)
exercise the production candidate pipeline through reviewer rejection, one repair,
fresh verification and either approval or normal repair-budget exhaustion. They
address the local correction-loop gap in P-07 and M3-02 without external credentials
or historical evaluation data.

Both cases run actual Docker isolation preflight, baseline checks, and separate
full-suite and criterion checks for each candidate: six container operations per
case. The first candidate passes its behavior tests but lacks a required docstring;
a scripted independent-review response requests that correction. The next builder
request receives the previous candidate and exact rejection evidence. A successful
repair adds the required docstring; the exhaustion case changes the implementation
but leaves that finding unresolved and receives a second rejection.

Assertions check distinct candidate snapshot digests, four fresh collector nonces
and immutable test receipts, original regression preservation, both retained
attempts, and the exact evidence provided to each fresh review request. The approved
result passes the production manifest validator. Exhaustion returns `FAILED` with
`Correction budget exhausted`, without a candidate readiness manifest or another
model request. Every created container is absent afterward.

HTTP responses are controlled through `httpx.MockTransport`; structured request
construction, parsing, reservation and settlement use the real model adapter and
SQLite store. A fresh database engine verifies all four operations remain settled,
including rejected reviews, with exact context digests and per-call usage. Each
case retains 12,000 microdollars at deliberately configured fixture rates and zero
outstanding reservation. These are test accounting values, not provider charges.
There are no paid or external provider calls.

## Recorded local check

At production source `31788de`, both new cases passed in **19.19 seconds**, using
the existing collector image
`sha256:136340a9d0e974bb74700fd4caa874f4fefd757b6683e6347e83bf8228041138`.
No production source change was needed. This is a focused two-test result, not a
new full-suite count or hosted-CI claim.

To repeat with an already built trusted collector image, set `TEST_SANDBOX_IMAGE`
to its immutable digest and run:

```sh
uv run --no-sync python -m pytest tests/test_correction_loop.py -q
```

The cases explicitly skip when no image is configured. They prove controlled local
pipeline behavior and accounting, not model judgment quality, live provider billing,
Temporal worker-process recovery, GitHub/Linear handoff, or human pilot observation.
They do not establish independent review's effectiveness on historical tasks.
