# Separately authorized, metered candidate scoring

Historical qualification permits a particular use of evidence. It does not authorize
Docker execution or allocate a scoring budget. `evaluation.scoring_execution` supplies
a separate trusted scorer boundary for exactly three operations: isolation preflight,
the complete acceptance command, and the complete regression command. The harness
continues to own candidate policy, protected tests, frozen collection checks and verdicts.
This controller cannot narrow the regression suite or grant task admission.

## Trusted Python API

Construct a `ScoringExecution` with the dedicated `EvaluationExecutionStore`, a current
`authorization_provider` callback returning `ScoringAuthorization`, and a trusted current
clock. The harness requires this concrete object in addition to `QualificationAuthority`.
After its static candidate gates, it calls:

```python
execution.validate(task, candidate, qualification_authority, output_artifacts)
result = await execution.run_operation("preflight", preflight_operation)
acceptance = await execution.run_operation("acceptance", acceptance_operation)
regression = await execution.run_operation("regression", regression_operation)
```

Each operation is a trusted callable accepting an operation ID and returning an awaitable
JSON dictionary. Verification uses that ID as the collector workflow identity. The
controller returns the original operation dictionary, including known failed test results;
settled infrastructure accounting never changes a failed test into a passing verdict.
`operation_id(stage)` exposes the same ID for the harness's receipt checks.

`ScoringAuthorization` pins:

- The qualification artifact, qualification task-manifest digest and exact candidate digest.
- Current execution-configuration and preparation-policy digests.
- A separate account ID, the task budget, infrastructure and combined cost ceilings.
- Infrastructure microdollars per second, immutable rate-card version and issue/expiry times.

The task-manifest digest is `qualification_task_digest(task.model_dump(mode="json"))`;
the candidate digest is `digest_json(candidate)`. The scoring budget must equal the task's
budget and remain within current operator limits. The account must differ from the
qualification account. Creating an account or constructing a grant from untrusted data
does not confer authority: the grant provider and scorer-owned callables remain trusted
control-plane code. No model/provider call is made by this module.

Setup checks concrete current authority with `purpose="scoring"`, including rejection of
synthetic/unadmitted qualification, before creating bookkeeping. It binds the grant, task,
candidate, qualification and evaluator/worker root identities to an immutable checkpoint.
All configured local repositories are excluded from evaluator artifact scopes. The SQLite
ledger cannot be located inside a worker root or configured local repository. Detailed
results remain evaluator-only because verification can expose withheld tests and output.

## Cost, cancellation and restart

The declared worst-case cost must fit both infrastructure and combined ceilings:
`(255 + 2 * (command_seconds + 240)) * microdollars_per_second`. Reservations occur per
operation, not atomically across the three-stage batch. Other separately authorized use
of the account can consume remaining budget and stop a later stage. There is no hierarchy
enforcing a campaign ceiling across accounts.

Preflight reserves 255 seconds; acceptance and regression each reserve the approved command
timeout plus 240 seconds of bounded runner overhead. Measurement uses a monotonic clock
around the entire awaited callable, including cleanup, rounded upward to milliseconds.
The ledger charges `ceil(milliseconds * rate / 1000)`, with zero model tokens. These are
controller-measured local estimates, not cloud invoices or host attestations. An observed
duration exceeding its reservation is refused without truncation or budget release.

The grant has an absolute deadline: the earlier of its expiry and issue time plus task
wall time. Current grant identity, settings, policy, private scopes and qualification
authority are rechecked before each operation, during active work, and before returning
cached or newly settled output. Revocation cancels the retained child and awaits cleanup.
Repeated cancellation cannot detach that cleanup join; cleanup failure becomes a sanitized
failure. Process death and unavailable hosts still require separate operational recovery.

Each stage has a distinct immutable operation/input binding. Acceptance requires settled
preflight; regression requires both earlier stages settled. Exact settled operations return
their recorded result without another Docker call, including after a lost settlement
acknowledgement. An unresolved reservation remains `UNKNOWN` and refuses re-execution.
Cancellation, failure without a returned result, invalid output or uncertain cleanup retains
the full reservation. A changed grant/candidate cannot reuse the same account checkpoint.
Expired scoring grants cannot renew execution by resuming an account.

## Validation boundary

Focused tests explicitly replace the expensive qualification authority boundary with a
controlled synthetic fixture, then exercise the real SQLite ledger and scoring controller.
They cover three-stage accounting, exact cached reuse, changed bindings, grants and scopes,
stage order, active expiry/revocation, repeated cancellation, cleanup failure and settlement
acknowledgement loss. They do not establish historical admission, actual Docker isolation,
provider spend or benchmark success. Genuine complete-chain and Docker scoring evidence
belongs to the qualification-controller integration tests, separately reported when run.
