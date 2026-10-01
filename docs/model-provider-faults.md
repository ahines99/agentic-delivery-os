# Durable model-provider fault drill

`tests/test_model_postgres_faults.py` exercises the production model adapter and actual
PostgreSQL usage ledger with a controlled HTTP transport. On 2026-09-28, all five
cases passed in 1.53 seconds. No external request or paid model call occurred.

| Injected boundary | Durable observation through a fresh database engine |
| --- | --- |
| HTTP 429 | Reservation retained; same logical operation cannot issue a second request |
| HTTP 503 | Reservation retained; same logical operation cannot issue a second request |
| Response timeout | Unknown outcome retains reservation; retry is denied before transport |
| Cancellation after transport entry | Cancellation propagates; reservation survives; reissue denied |
| Settlement committed, acknowledgement lost | Actual usage stays settled; retry returns cached structured output with no second request |

Each test uses a unique synthetic workflow and logical operation. The first four cases
verify `RESERVED`, positive reserved cost, zero settled cost and unchanged workflow
accounting after the refused retry. This is conservative accounting: zero settled cost
does not mean the provider charged nothing. Even the controlled 429/503 responses do
not release the reservation automatically. The final case verifies `SETTLED`, the exact
synthetic 3,000-microdollar usage, zero reservation and unchanged accounting on retry.
The transport call count must remain one in every case.

Use an authorized disposable PostgreSQL environment and run:

```text
python -m pytest tests/test_model_postgres_faults.py -q
```

`TEST_DATABASE_URL` must identify PostgreSQL; otherwise tests explicitly skip. Synthetic
rows remain as drill evidence, with pending/unknown work visibly unsettled. The tests do
not resolve, delete or alter existing workflows or actual provider billing records.

These are injected adapter/ledger boundary failures, not actual provider outages, process
kills or network partitions. They establish that a fresh database consumer cannot turn
these unknown outcomes into automatic duplicate billable calls. They do not reconcile a
real provider invoice, prove cancellation of a remote generation, or close all P-12 and
recovery gates. Actual unknown outcomes still require reconciliation before retry.
