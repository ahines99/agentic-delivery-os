# Publisher-process loss and reconciliation

The owned test in [test_publication_process_loss.py](../tests/test_publication_process_loss.py)
abruptly exits a real Python publisher process after a controlled provider accepts
branch creation, PR creation, or the final PR read. The provider fixture persists its
state with flush/fsync before `os._exit`; the publisher never receives that response
and its `finally` blocks do not run. A second Python process reconstructs settings,
loads the same immutable candidate artifacts and calls the production publisher
against the retained provider state.

All three cases passed in **5.52 seconds** on 2026-09-30, using application source
`6b74944`. Each recovery retained exactly one branch creation and one draft PR,
confirmed the original manifest/head binding, and performed the authoritative final
read. The PR stayed unmerged. The crashed process wrote no success result and did
not revoke its synthetic token; the recovery process revoked its own token normally.
The existing publisher required no production code change.

The subsequent GitHub adapter/process-loss selection passed **44 tests in 12.24
seconds**. Ruff, formatting and mypy passed. These cases extend verification of the
existing publisher; they do not change application source.

This supplements the earlier in-process HTTP timeout tests with actual loss of
process memory and bypassed cleanup. It uses a durable **controlled provider fixture**,
not actual GitHub writes, real installation credentials, a network outage or an
invoice. The test generates its own signing key, and every HTTP request stays inside
the mock transport. No model, historical task or live database is used.

In this original drill the caller deliberately invokes the publisher again with the
original operation identity and candidate. It proves broker reconciliation only.
The subsequent [workflow recovery](workflow-publication-recovery.md) adds and tests
automatic reconciliation by a replacement Temporal worker, with a stricter rule:
only an already-existing PR can be confirmed automatically. A branch-only outcome
stays blocked. Both are distinct from the killed-candidate worker recovery recorded
in [worker-process-loss.md](worker-process-loss.md).

Run the focused test with the project environment:

```text
python -m pytest tests/test_publication_process_loss.py -q
```
