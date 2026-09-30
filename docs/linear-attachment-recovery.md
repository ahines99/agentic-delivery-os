# Linear PR-link response recovery

If Linear accepts the PR attachment but its response is lost, the handoff now makes
one read-back request instead of stopping immediately or repeating the write. The
request reads the current ticket and the URL's attachment connection together.
It requires the exact issue/URL pair, one unarchived matching attachment and a
complete response of at most 100 attachments. Changed ticket text, team or assignment,
revoked approval, changed CI, incomplete results and failed reads cannot authorize
the review-state update. An already-current review state needs no status mutation.

Linear documents issue/URL attachment upserts and URL lookup in its
[attachment API](https://linear.app/developers/attachments). Read-only introspection
confirmed the pagination arguments, and the implemented read-back query confirmed
PER-13's existing PR #6 link against the live API. That check made no mutations and
does not simulate a real vendor outage.

Verification on 2026-09-30:

- The adapter/activity selection passed 65 tests, including 17 attachment cases:
  accepted and missing writes, already-current state, two lost acknowledgements,
  wrong issue/URL, archived/duplicate links, incomplete or malformed responses,
  changed requirements/assignment, revoked authority and explicit rejection.
  The subsequent expanded monitor/ingress/adapter/activity selection passed 163
  tests in 14.64 seconds. Ruff, formatting and mypy also passed.
- Five scenarios passed through actual PostgreSQL and Temporal in 10.43 seconds:
  accepted link, absent link, changed CI, changed ticket and expired approval.
  They execute the real Linear adapter and handoff activity against controlled
  HTTP responses, retain intent/result artifacts, read terminal state through a
  fresh database engine, and replay each workflow history. Only the accepted case
  reaches HUMAN_REVIEW and performs one status mutation. Every case attempts the
  attachment write exactly once.
- The integration fixture supplies owned candidate/publication/CI records. It
  neither calls a model nor creates a remote PR. Its disposable database and task
  queues are separate from the installed service.

An unconfirmed link remains UNKNOWN and the workflow stops at POLICY_BLOCKED.
Recovery does not erase the original uncertainty through blind retries, provide
merge authority, or establish arbitrary provider recovery. Full regression and
installation status are recorded in [implementation status](implementation-status.md).
