# Implementation and verification status

Updated 2026-09-30 UTC during continued controlled implementation. This is the current capability record;
the original milestone documents remain the release targets. Source code alone is not a passed
integration or production release gate.

The local service is now running `f3bcbc6`, including manual acceptance and the
worker-independent container lifetime. The [idle upgrade record](local-runtime-upgrade.md)
confirms readiness, fresh Temporal pollers, advancing Linear detection, authenticated
manual-review routing and preserved exact PR #6/#7 handoff bindings. Application
source is identical to the fully passing `430bc19` CI below. The installed head's
[combined CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36740262123)
subsequently passed Python 3.12/3.13 (3,304 tests and 136 explicit skips each), all
136 service integration tests, package builds and secret scanning. The full Windows
feature runs and later test-fixture correction remain separately tracked.

The [terminal outbox redelivery follow-up](postgres-faults.md#terminal-redelivery-follow-up-2026-09-30)
passed the expanded 15-case PostgreSQL/Temporal fault suite in 8.43 seconds. All three
lost-acknowledgement boundaries now also prove that redelivery after completion is
rejected by Temporal without a new run, changed terminal state or altered history.
The existing dispatcher behavior required no production code change.

The [Linear PR-link recovery](linear-attachment-recovery.md) follow-up adds one
bounded confirming read after a lost attachment response, with current ticket and
authorization checks before any status update. The expanded monitor, ingress,
adapter and activity selection passed 163 tests; five actual PostgreSQL/Temporal
fault scenarios passed and replayed. A
read-only live query confirmed the existing PER-13/PR #6 attachment. Full regression
verification and installation of this follow-up remain pending.

Linear intake now rechecks eligibility after assignment. A concurrent completion,
cancellation or start cannot be admitted from the earlier discovery record once
observed on read-back. An unavailable assignment response triggers one confirming
read, with identity/team/text/assignee checks; no assignment mutation is repeated
within that scan. The focused Linear monitor/adapter/ingress suite passed 129 tests,
including controlled HTTP faults, SQLite persistence and fresh-client/store replay.
Ruff, formatting and mypy passed. This is not an atomic provider lock or a live
provider-fault exercise. Source `0bcd0ee` was installed through an idle supervised
restart; readiness returned, Linear polling advanced and both existing review
handoffs remained persisted. Its full Windows suite at `91f1b21` completed with
3,205 passed and 130 explicit skips in 4,459.49 seconds. [Hosted CI at
`91f1b21`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36732891287)
passed Python 3.12 and 3.13 (3,215 tests and 120 explicit skips each), all 120 service
integration tests, package builds and secret scanning. This includes the intake,
backup-selection and model-diagnostic fixes described below.

Manual acceptance is implemented at `3550009`: a draft can carry visibly pending
human criteria, authenticated decisions bind to exact revisions and current evidence,
and Linear handoff waits for those decisions plus current CI. The focused suite passed
270 tests with six explicit Docker skips; eight actual PostgreSQL/Temporal scenarios
passed, including restart, stale/revoked decisions, cancellation and unknown GitHub
update outcome. [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36735702473)
passed Python 3.12 and 3.13 (3,294 tests and 129 explicit skips each), all 129 service
integration tests, package builds and secret scanning. Its original full Windows run
finished with 3,280 passed, 139 skipped and four failed in 5,019.52 seconds. All four
failures are the calibration fixture's five-second startup wait described below;
none is a manual-acceptance assertion failure. These are owned scripted operator identities, not a human pilot
signoff. [Operator instructions](manual-acceptance.md) describe the API.

The follow-on sandbox fix at `430bc19` replaces the two-hour keepalive with the approved
command timeout plus a fixed 60-second lifecycle allowance. Ten profile cases and a
real Docker worker-tree kill case passed together (11 tests in 75.17 seconds); the
container exited without replacement-worker cleanup. Its full Windows suite finished
with 3,294 passed and 140 explicit skips in 4,898.68 seconds. Complete
[hosted verification](https://github.com/ahines99/agentic-delivery-os/actions/runs/36737373590)
passed Python 3.12/3.13 (3,304 tests and 130 explicit skips each), all 130 service
integration tests, package builds and secret scanning. See
[ADR-031](adr/ADR-031-container-lifetime.md) for limits. Both features are installed.

A focused Windows rerun reproduced three failures among four adjudication-calibration
guard cases. A single-case traceback confirmed a timeout at the five-second wait for
the mocked request to start, before the in-flight behavior under test. The fixture
now allows thirty seconds for startup, surfaces an earlier preparation failure, and
always cancels/awaits its helper tasks. All four cases then passed in 31.83 seconds;
Ruff, format and mypy passed. Production deadlines, cancellation assertions and
retained-unknown-cost requirements are unchanged. The manual-feature full run ended
with those four startup timeouts; the later container-lifetime run passed on its
original revision. The targeted result does not erase the failed run.

The [compromised-builder admission matrix](product-admission-controls.md) subsequently
passed six actual Docker cases in 21.92 seconds on unchanged application source
`430bc19`. Hostile ticket/README instructions reach a controlled model response;
sensitive code, protected CI/tests, dynamic execution and credential-shaped output
are then refused before candidate execution or review. The owned broker canary stays
out of the model context and baseline container; real baseline receipts and fixture
usage remain persisted. This is named-control evidence, not general injection resistance
or live model behavior. The combined `f3bcbc6` CI above includes all six cases in its
passing service integration job.

Distribution staging at `430bc19` passed in a fresh non-editable Python 3.12.10
environment with 31 hash-locked runtime dependencies. All three CLI help entry points
passed, and the manual acceptance, GitHub finalizer and Docker modules resolved only
inside the installed wheel. That installed package passed all seven actual Docker
preflight controls on the pinned runtime image. Wheel SHA-256:
`376854689419e7129f199c42641539bec4388b1094601fd0dce3e8c0c5f431b1`.
This staging made no provider calls and did not restart the live service.

A metadata-only registry check on 2026-09-30 confirmed the development evaluation's
USD 25 cap currently contains USD 6.467064 in closed envelopes and USD 18.030201 in
two active envelopes, leaving USD 0.502735 for new envelopes. The active amount is
reserved capacity, not a claim that USD 18 was billed. Earlier unknown operations
remain unresolved after provider billing restoration. No cap, grant, expiry, ledger
or reservation was changed. This prospective registry excludes older liabilities
and does not establish complete program cost. Further historical qualification needs
sufficient current authorized capacity; live product ticket budgets are separate.

The earlier full Windows run collected at `0adc93d` completed: 3,145 passed and
126 explicit service/platform skips in 4,642.41 seconds. Later tests and fixes are
recorded separately; this local result does not cover the latest source.

Model failure diagnostics now include fixed, sanitized HTTP error categories and a
bounded Anthropic billing/quota hint. Existing provider observations, accounting and
retry rules are unchanged. The focused model/receipt/reconciliation suite passed
121 tests with one explicit PostgreSQL skip. Five actual PostgreSQL/Temporal fault
cases passed in 21.19 seconds, including billing-response classification in retained
workflow failure history, withheld provider-text canary, unchanged reservation,
denied reissue and successful history replay. The subsequent `91f1b21` CI above
covers this source.

Earlier complete hosted verification: [CI at `e611917`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36724207546)
passed Python 3.12/3.13 (3,165 tests and 119 explicit integration skips each), all
119 service integration tests, and secret scanning. This covers planning cancellation
and Linear status-response recovery. The later backup selection and diagnostic changes
have their focused verification recorded here; they are not included in that CI SHA.

Provider response-loss follow-up (2026-09-30): the Linear adapter now performs one
read-back after an unavailable status-update response. It confirms only the requested
review state with unchanged ticket text/team/assignment and current authorization;
it never repeats the status mutation. The handoff activity still checks current CI
afterward. Controlled transport and SQLite/artifact tests cover accepted updates,
unapplied updates, changed requirements, revoked authorization, failed read-back and
CI invalidation during reconciliation. At that revision, attachment-response uncertainty
remained UNKNOWN; the subsequent bounded attachment read-back is recorded above.
Three additional GitHub adapter cases lose acknowledgements after branch creation,
PR creation or final read-back; fresh clients reconcile one branch and one draft PR.
The combined adapter/handoff suite passed 89 tests. These are controlled provider
tests, not a new live provider fault drill. Source `e611917` was installed through an idle
supervised restart; readiness returned and Linear polling advanced while both existing
review handoffs remained persisted. [Full CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36724207546)
for this change passed, as recorded above.

Live backup follow-up (2026-09-30): the backup script now accepts an explicit local
source database and artifact directory, so it can capture the installed `delivery_live`
service instead of always selecting the development database. The 25 focused tests
passed. An actual idle, quiescent drill captured a 103,687-byte dump and 347 artifacts
(1,280,975 bytes), restored matching counts for all 12 tables and schema revision 0006
in a disposable database, then verified its removal. The supervised service restarted;
readiness returned and Linear polling advanced. See the [recorded drill](local-backup.md#installed-live-database-exercise).
This does not establish Temporal or provider-state recovery.

Distribution verification at `cea4025`: wheel and source archive built successfully,
and their inventories contained no private environment, key or `.local` paths. The
wheel installed in a fresh Python 3.12.10 environment with hash-checked locked runtime
dependencies. Imports came from that installed package; all three CLI help commands,
all three offline intake outcomes, and bundled migration to revision `0006` passed.
This checks packaging independently of the development checkout; it makes no live
provider or historical-evaluation claim.

Planning cancellation follow-up (2026-09-30): the planning activity previously lacked
the heartbeat/timeout pair required for Temporal cancellation delivery. An owned
regression with actual Temporal/PostgreSQL and a held controlled model transport
failed its 25-second cancellation wait before the fix. Planning now heartbeats during
snapshot/model work; new workflows use a 20-second heartbeat timeout, with a version
marker preserving older histories. The regression then passed in 18.47 seconds total:
local request cancellation, CANCELLED projection, APPLIED command, retained unresolved
reservation/observation, one model invocation, denied reissue through a fresh database
connection, and successful history replay. The test used a separate disposable database
and made no provider call. This does not prove remote-provider cancellation or invoice
reconciliation. Another 71 focused authorization/monitor/handoff/replay tests passed;
Ruff, formatting and mypy passed. Source `0adc93d` was loaded by a supervised service
restart after confirming that all live workflows were terminal. API/database readiness
returned and the configured Linear cursor advanced; both completed review handoffs
remained persisted. The private restart record retains the new launcher identity and
observations. Full CI at `e611917` subsequently passed this change.

The SDK requirement is documented in Temporal's
[heartbeating and cancellation guide](https://github.com/temporalio/sdk-python#heartbeating-and-cancellation).

The same real Temporal/PostgreSQL test now also exercises controlled HTTP 429, HTTP 503
and lost-response failures. All four cases passed in 20.96 seconds. Each ends explicitly
in CANCELLED or FAILED, retains the unresolved reservation and provider observation,
starts no build/publication, performs one model invocation, refuses reissue through a
fresh store, and replays its complete workflow history. This extends the earlier
ledger-only provider-fault tests into the actual workflow without paid provider calls.

Earlier complete hosted verification: [CI at `81fd892`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36718387365)
passed Python 3.12/3.13 (3,155 tests and 115 explicit skips each), actual service
integration and secret scanning. The corresponding local package-profile suite passed
3,143 tests with 125 explicit Windows/service skips. The subsequent chronology fix at
`ec72597` passed 43 focused controller/admission tests with one explicit Docker skip,
Ruff, formatting, mypy and package builds; the hosted run above now covers that fix.
The later planning-cancellation change is tracked separately above.

Provider availability at 2026-09-30 13:59 UTC: the next historical review and one
owned diagnostic returned HTTP 400. The diagnostic recorded a billing/credit indicator;
no raw provider message or historical contents were exposed. Both reservations remain
unresolved and no historical retry was issued. After the owner restored billing, a
new owned diagnostic passed with HTTP 200, 1,565 settled microdollars and no reservation.
Model access and polling are available again; the earlier failed operations retain
their unresolved accounting rather than being erased.

Five historical development tasks have now completed qualification. The three qualified
markdownify tasks passed a freshly ordered runtime matrix, two independent reviews
and authority validation; an earlier late-plan attempt and its costs remain retained.
No historical scoring or campaign ran. See the [protected attempt record](historical-development-attempts.md).

Earlier runtime verification: [CI at `c03a945`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36664407290)
passed both Python versions (3,114 tests and 114 explicit skips each), 114 actual service
integration tests and secret scanning. This includes automatic-runtime, Windows snapshot,
Linear PR-link and local lint/format correction changes. The earlier
[CI at `5321f4b`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36655858237)
includes the [campaign journal](campaign-journal.md),
[completed semantic reader](semantic-consumption.md) and [whole-attempt reader](completed-attempt-reporting.md).
They reconstruct original outcomes, early failures and optional exact adjudication under
current report permission, without renewing execution or dropping costs. The subsequent
[serial dispatcher](campaign-dispatch.md) passed all 69 focused journal/dispatch tests,
including process exit, cancellation, revoked authority, optional adjudication and lost
completion acknowledgement. Ruff/format (335 files), mypy (105 sources) and package build
passed, followed by the hosted result above. The [bounded phase driver](campaign-phase.md)
then passed 17 focused tests, including one concrete dispatcher/coordinator path. It schedules
an already-authorized phase without promoting it or retrying uncertainty. Complete evaluation reporting,
numerical promotion and actual historical phase execution remain open. Earlier live calibration and data grants are historical evidence;
expired authority cannot authorize current consumption or new runs.

[Accounting inspection and preparation inventories](campaign-accounting.md) passed
26 focused tests, including actual SQLite/PostgreSQL snapshot behavior under concurrent
settlement. A bounded real metadata inventory then captured 33 accounts/214 operations
across the three previously enumerated evaluation SQLite ledgers. It retained 9,424,997
settled microdollars and 948,834 reserved microdollars across five unresolved operations,
without reading model result payloads, mutating ledgers or making paid calls. Full program
inventory coverage and cost promotion remain open.

An optional whole-ledger census now checks for accounts omitted from the selected inventory,
including zero-cost accounts, and detects duplicate account IDs across declared ledgers.
The aggregate report requires separate whole-ledger permission, compares metadata before
and after reconstruction, and keeps census totals separate from selected totals. It still
cannot attest that every program ledger was declared; prospective registry enforcement and
cost promotion remain open. See [accounting scope](campaign-accounting.md#declared-ledger-census).

A [prospective program budget registry](program-budget.md) now reserves account envelopes
across approved SQLite/PostgreSQL ledger targets before account creation. New reservations
require an active envelope; irreversible local closure and concrete settled-cost proof precede
capacity release. Partial creation/closure and unknown usage retain their liability. Legacy
ledgers remain unchanged. All 131 registry/accounting/allocation checks passed with real
PostgreSQL, including campaign allocator admission under both protocols. Historical liability
incorporation and complete program-cost promotion remain open. Supported execution entry points
now require enrollment under [ADR-021](adr/ADR-021-required-evaluation-program-enrollment.md),
including existing-account stages and resumed calibration. Legacy evidence inspection stays
separate. Focused denial/resume checks and 63 registry/allocation tests with real PostgreSQL
passed. The 13-module execution regression scope passed 453 tests with 12 explicit service
skips; the hosted result above subsequently passed the complete service suite, including
the remaining Docker cases. Later legacy archival and registry incorporation need new-head CI.

A [program accounting reader](program-accounting.md) now reconciles registry envelopes
with complete concrete ledger snapshots and local lifecycle markers, under separate full-scope
metadata permission. It preserves pending creation/activation/closure, refuses unexplained
missing/extra accounts and mismatched costs, and rereads every ledger/registry before returning.
Campaign reports can include this separate view without claiming historical costs or promotion.
The combined reader/registry/accounting/campaign scope passed 84 tests with actual PostgreSQL;
the final 23-case focused scope also passed after adding registry-change, permission-revocation
and unenrolled-target cases. All live historical enrollment and cost gates remain open.

The [prospective readiness policy](adr/ADR-018-prospective-readiness-reporting.md) passed
15 focused tests. It pins A/B candidate-status declarations before phase opening or
allocation and refuses retrospective insertion. This supplies the frozen reporting rule;
the report below provides concrete all-assignment consumption. Promotion remains open.
The hosted result above includes these accounting/policy changes.

The [all-assignment report](campaign-reporting.md) now consumes concrete completed-attempt
proof, the original readiness policy, every canonical account and selected preparation
inventories. Seventeen focused cases cover missing outcomes, retained uncertainty, chronology,
successful/failed scoring and exact adjudication. Three existing execution/consumption checks
also passed. It does not attest complete program-ledger coverage or supply numerical,
statistical, operational or pilot promotion. The hosted result above includes this report.
This hosted result includes the whole-ledger census, prospective phase statistics and
requirement inventory, criterion judgments, prospective program budgets and concrete program
reconciliation, required execution-entry enrollment and final-candidate criterion test counts.
Later legacy archival and schema-2 program policies need their own exact-head verification.

Prospective [phase statistics](adr/ADR-019-prospective-phase-statistics.md) now pin the bootstrap
method and campaign seed before execution. The version-2 completed-attempt reader exposes
verified acceptance/regression results and final checkpoint timing. Reports keep phases and
stability attempts separate, retain missing/unknown costs, and supply primary Wilson and
paired success/cost intervals plus individual numeric checks. All 69 combined policy,
statistics, completed-attempt, aggregate-report and ledger-coverage checks passed in
456.39 seconds. Lint/format, types and builds also passed; exact-head hosted CI remains required.
Criterion-level coverage, infrastructure incident classification, full program cost enforcement,
operational gates and pilot signoff remain open. No historical result or promotion is claimed.

A [prospective requirement inventory](campaign-criterion-inventory.md) now captures complete
criterion denominators under current qualification, binds them to the original campaign and
registration, and pins its reference before execution. Reports retain counts for unrun tasks
without loading protected task contexts; policies without an inventory retain unknown counts.
The combined inventory/policy/statistics/reporting suite passed 66 tests in 188.43 seconds;
one additional capture-permission revocation case passed in 5.90 seconds. Qualification is an
explicit owned-fixture boundary in these inventory tests. No historical inventory was captured,
and complete required criterion evidence remains unfinished. A subsequent
[criterion judgment consumer](criterion-judgments.md) carries actual validated semantic
status counts through whole-attempt reporting and checks them against the frozen inventory.
Unscored requirements remain visible; semantic judgments do not supply human decisions or
complete execution evidence. Its counts/statistics/inventory scope passed 50 tests; the
consumer/whole-attempt/report scope passed 60 with four fixture setup errors, and the
corrected four aggregate cases then passed. Production code did not change between those
runs. See the linked record for timings and the retained setup error. New-head full CI
and independent review remain outstanding.

The [transaction/outbox fault matrix](postgres-faults.md) also passed 12 scoped actual
PostgreSQL/Temporal cases, and [model-provider ledger faults](model-provider-faults.md) passed
five PostgreSQL cases with controlled HTTP responses. These preserve rollback, deduplication and
uncertain usage accounting across fresh consumers; injected exceptions do not establish process-
crash recovery or live-provider reconciliation.

## Implemented and exercised

[Linear clarification edits](adr/ADR-028-linear-clarification-edits.md) now resume an
already paused workflow from verified ticket text, preserving its original budget.
PER-14 exercised actual ambiguity, one source edit, one applied clarification command
and replanning in the same workflow. Sixty-nine focused monitor/authorization/control-
plane tests passed; a separate 55-case scope including actual Temporal restart/replay
also passed. Counts overlap. The revised ticket's final delivery remains in progress.

[Outbound publication observation](adr/ADR-027-outbound-publication-observation.md)
now lets the local service notice closed, merged or changed PRs without a webhook.
The real App read-only path reconciled the five retained product PRs: #2?#5 CLOSED,
#6 DRAFT_HANDOFF. No external mutation or model call occurred. Polling is enabled in
the supervised local service. The delivery regression scope passed 114 tests; the
CI/storage/monitor scope passed 85 tests (overlapping counts). Ruff, format, mypy
and staged secret scanning passed. Full hosted verification for this follow-up is
separate from the earlier c03a945 result. Actual human merge and signed callbacks
remain distinct unexercised provider scenarios.

Live automatic intake has created, assigned, planned, automatically approved, built and
independently reviewed owned Linear tickets, publishing real App-authored PRs. The first
PRs were closed after CI exposed a startup-test scheduling race and missing local quality
checks; none reached review-ready status. Their attempts, costs and PR histories remain.
The runtime test now waits for worker startup, and [ADR-026](adr/ADR-026-local-quality-checks.md)
adds image-owned Ruff check/format-check commands to the existing correction loop.
All 182 verification/pipeline/authorization/monitor checks passed with the actual pinned
Docker image, followed by 68 GitHub/replay checks. Three real Docker pipeline cases passed
complete manifest validation for flat, src and mixed pytest/Ruff profiles. These scoped
counts overlap. Full hosted CI subsequently passed at the revision linked above.
The [live record](live-automatic-delivery.md) confirms the subsequent PER-13 run:
App-authored PR #6 passed all four exact-head checks, and the runtime reached
`HUMAN_REVIEW` at 2026-09-30 04:04:04 UTC. Linear readback confirmed In Review and one
PR attachment. Three settled model operations cost $0.215420, with no reservation.
The supervised service recovered during CI wait without another attempt or charge.

[Automatic Linear delivery](automatic-delivery.md) now adds a bounded outbound monitor,
restart cursor, idempotent intake, explicit low-risk automatic approval and a combined
local service command. This follows the owner's request in [ADR-025](adr/ADR-025-automatic-linear-delivery.md).
Seventy-five monitor/runtime/credential/control-plane/authorization tests passed; the
127-case pipeline/GitHub/CI/replay regression scope also passed. An initial cancellation
test cancelled before the newly sequenced services started; the corrected test waits
for active services and verifies their shutdown. The Windows startup script parses.
Live automatic ticket-to-PR execution and full implementation CI subsequently passed, as recorded above.

The earlier unchanged Windows full run at `4d71ce3` completed with 2,963 passed and
101 explicit skips in 4,292.95 seconds. It does not cover subsequent changes.

The [combined webhook gateway](linear-ingress.md) now routes both Linear intake and
GitHub PR/CI callbacks to the existing private API. Its signed GitHub regression test
passes through both gateway and actual API into SQLite, retains one observation on
duplicate delivery and rejects modified signed bytes. All 130 ingress, GitHub-check
and control-plane regression tests passed; lint, formatting and type checks passed.
The earlier Linear-only entry point retains its existing behavior. Live GitHub App
delivery is verified through outbound polling; persistent HTTPS hosting and live signed
post-merge/close callbacks remain unconfigured.

[Joint criterion evidence](criterion-acceptance-evidence.md) now joins final-candidate tests
and independent semantic findings by criterion after concrete whole-attempt reconstruction.
The explicitly selected [ADR-024 profile](adr/ADR-024-prospective-criterion-evidence-gates.md)
checks complete recorded dispositions and passing evidence for every declared-ready candidate.
Passing coverage still uses all assigned requirements; a documented failure does not become a
pass. Manual criteria remain pending without human decisions. The final 20-case joint scope and
44 concrete reader/reporting cases passed, alongside inventory/policy regressions. Original
policies cannot acquire this profile retrospectively. New-head full CI, infrastructure,
program-inventory/cost, operational, corpus and pilot promotion requirements remain open.

The new [schema-2 program policy](program-legacy-liabilities.md) now pins a concrete archived
ledger inventory at creation and subtracts all its settled/reserved liability from available
capacity. Old policy bytes and registries remain unchanged. Current program/campaign reports
reconstruct that historical selection under separate current permission and keep it separate
from prospective observed usage. The final combined accounting scope passed 179 tests with
actual PostgreSQL and no skips; eight reporting cases also passed. Full new-revision CI,
authorized live archival/import, complete inventory attestation and invoice reconciliation
remain open. This supersedes earlier statements that no historical registry path is implemented;
it does not imply any real historical ledger has been archived or imported.

[Legacy accounting archival](legacy-accounting.md) now provides an explicit irreversible
transition and concrete metadata-only liability reader. It preserves original records and
unknown reservations, fences current writers including handles opened before archival, and
retains the archive when permission is lost after commit. The final store/registry/accounting
scope passed 149 tests with actual PostgreSQL and no skips. This was owned test data only;
live archival, older-writer quiescence, actual registry incorporation and full cost promotion remain
unfinished. [ADR-022](adr/ADR-022-legacy-ledger-archival.md) records the authority and limits.

The [final-candidate criterion test reader](criterion-execution-evidence.md) now exports
execution counts only after concrete receipt replay reproduces the sealed candidate. It
matches those counts to the frozen requirement inventory, retains missing assignments and
failed or unexecuted tests, and rejects evidence from earlier repair snapshots. These are
verified executions of builder-proposed tests, not complete criterion acceptance or human
approval. The reducer/statistics scope passed 25 tests; eight concrete reader cases and four
aggregate cases passed, including the final composition with mandatory program enrollment.
The initial four aggregate fixture setup failures and corrected results are retained in E158
and E159 of the completion audit. Full CI for the combined revision remains required.

The [local correction-loop tests](correction-loop.md) now cover rejection, successful
repair with fresh evidence and normal exhaustion. A [shared candidate engine](candidate-arms.md)
adds a builder-only evaluation mode while keeping product delivery review-mandatory.
It also protects conventional nested/suffix original-test layouts and refuses
duplicate criterion verdicts. This is candidate generation, not campaign execution.

An [actual worker-loss drill](worker-process-loss.md) found and then verified a fix
for orphaned candidate containers: a separate bounded activity removes exact
workflow-owned containers, or records cleanup as `UNKNOWN`. Pre-fix and current
histories replay. The proof is for killed workers on the current host; distributed
fencing remains open. [Schema-3 campaign freezing](evaluation-campaign.md#explicit-execution-budget-contract)
separates immutable qualification budgets from comparison limits but grants no
execution permission.

The combined service-enabled suite at `3956b29` passed **1997 tests with ten explicit
Windows skips** in 957.33 seconds. It exercised actual PostgreSQL, Temporal and Docker;
the unique test database was removed and its absence verified. Ruff/format (267 files),
mypy (86 sources), locked dependencies, package build and new-commit secret scanning
passed. This includes the versioned scoring, protected context and owned runtime
changes below. It does not substitute for exact-head hosted CI or remaining release gates.

Hosted [CI at `9438b47`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36502328714)
passed all four checks: 2165 tests with 86 explicit skips on each Python version,
and 87 actual service integration tests. It retains production source `8555fcf`,
including the candidate/scoring executors, read-only inspection and adjudication
contracts. These overlapping scopes are not summed. Local full verification at `8555fcf`
finished with 2240 passed, ten Windows skips and one allocation-test setup failure: the
private driver used a database name outside the required `delivery_eval_` prefix.
The exact PostgreSQL allocation case then passed in 3.76 seconds with the corrected
dedicated database. Both original databases and the rerun database were dropped and
absence verified. The original full-run failure remains retained.

The [versioned scoring consumer](campaign-scoring.md) uses an existing frozen
attempt account and original deadline; it creates no additional spending capacity
and leaves legacy scoring unchanged. [Protected semantic contexts](semantic-scoring-context.md)
reconstruct candidate/receipt evidence and validate complete cited findings, but
do not execute independent scorers or establish semantic success. Five separately
authored [owned examples](semantic-scoring-examples.md) have also passed actual
[Docker preparation](owned-semantic-runtime.md), retaining exact receipts and costs.
They remain distinct from historical admission and model calibration.
[Canonical campaign allocation](campaign-allocation.md) now binds each ordinal to
one account on a pinned ledger, preserving its original deadline and capacity.
Owned tests include six concurrent PostgreSQL controllers. Partial recovery rejects
prior operations even if their recorded cost is zero. [Owned contexts](owned-semantic-context.md)
reconstruct the original runtime evidence under current policy. These integrated
changes passed 148 focused tests with one dedicated-PostgreSQL test skipped; its
separate actual PostgreSQL run passed. Full campaign execution and historical final
scoring remain unverified. [Purpose-specific calibration](semantic-calibration.md) has controlled
broker and actual owned Docker tests; its live outcome is recorded separately.
The first live calibration stopped on its third request with HTTP 400; a separate
small diagnostic returned a billing/spending-limit hint. Paid and unresolved usage
remain retained. After the user restored billing, a fresh one-call diagnostic
succeeded and a separately authorized five-case calibration completed. It failed:
three of five outputs were fully valid matches, with two citation-contract failures
and zero observed false-ready verdicts. The run settled 597,710 microdollars with
zero reservation. A later v2 citation-prompt run at 4,000 output tokens stopped at
truncation and was reconciled for cost only. The subsequent 6,000-output profile
completed all five valid outputs, with five overall verdict matches but four exact
finding-map matches and one mandatory failure. It settled 572,270 microdollars with
zero reservation. Both remain failed calibration evidence; live final scoring is
still gated at that checkpoint. A subsequent prospective Opus 5.5 configuration
with v3 instructions passed all five exact owned anchors with zero mandatory failures
and false-ready observations, settling 365,540 microdollars with no reservation.
Current read-only passing validation succeeded without writes or account changes.
Historical scoring and separately calibrated adjudication remain open. See the full
[record](semantic-calibration.md).

The [A/B execution adapter](campaign-candidate.md) now connects canonical allocation
to the shared engine, real broker accounting and Docker. Actual owned A and B repair
paths pass; full-source contexts must fit existing caps. The
[two-scorer executor](semantic-execution.md) uses two isolated initial contexts,
current concrete calibration and the same original attempt account/deadline.
Agreement may produce a semantic result; disagreement stays unresolved and invalid
or unknown reviews cannot be replaced. These are controlled execution capabilities,
not historical campaign results. The integrated candidate/scorer scope passed 72
tests, including actual Docker paths. [Read-only candidate inspection](candidate-inspection.md)
then passed all 43 tests after integration, without credentials or execution effects.
[Adjudication contracts and original dispute fixtures](semantic-adjudication-contracts.md)
passed 55 tests and independent review, but perform no model execution or calibration.
The [owned adjudication adapter](semantic-owned-adjudication.md) now binds those
unchanged hypothetical peer findings to verified actual owned runtime evidence,
without inventing reviewer operations. Root integration of the adapter, protected-path
scoring checks and affected consumers passed 138 tests with one optional Docker skip.
The separate [adjudication calibration controller](semantic-adjudication-calibration.md)
is implemented with controlled broker and real owned Docker tests. Live adjudicator
calibration, historical adjudication execution and the complete campaign remain open. A compatible per-call output
configuration and context profile must also fit the frozen total attempt caps; the
20,000-output calibration profile cannot reserve two final scorers inside a
20,000-output total attempt.

The latest acquisition-only extension passed 103 focused acquisition/import tests and
56 actual service integration tests (213.08 seconds), plus Ruff/format, mypy, locked
dependencies and fresh wheel installation. Its isolated offline whole suite passed
1420 tests with 62 service/Windows skips before the final cleanup guard and extra test;
the final focused run covers that last change. The earlier complete service-enabled
verification below remains recorded separately. See [E55–E56](completion-audit.md).

- Validated operator/repository configuration; hashed bearer credentials, repository/role checks,
  bounded intake bodies, pause flag, idempotency keys and queued commands.
- SQLAlchemy tables and Alembic migrations on actual PostgreSQL; transactional inbox/outbox,
  immutable input revisions, sequenced audit projections, model reservations and usage settlement.
- Temporal worker and dispatcher; persisted planning/approval waits, stale command rejection,
  clarification, cancellation, duplicate suppression and replay tests across worker restart.
- Explicit reruns of eligible terminal attempts with a separate attempt/budget and retained prior
  spend; uncertain publication blocks rerun. Canonical stored commands are resolved and authorized
  before workflow signals are applied. Plan approval requires the reviewer role and an absolute
  decision deadline; repeated invalid signals do not extend it. Approval use rechecks its expiry,
  current reviewer role/repository authorization, input revision and configuration before protected work.
- [ADR-008](adr/ADR-008-active-authorization-and-cancellation.md) adds worker configuration rereads,
  per-operation authorization and a five-second active-candidate monitor. Authorization failure
  cancels work and awaits cleanup; cleanup errors propagate rather than becoming successful
  cancellation. API/dispatcher settings still require restart. Polling cannot undo in-flight effects.
- Per-run configuration digests bind model, repository, budget and publication settings. A changed
  execution configuration fails the attempt and requires fresh planning/approval. Changed payloads
  for the same source ticket return conflict rather than creating parallel budget allocations.
  Projection idempotency checks include the complete audit event digest.
- Signed Linear webhook intake with workspace/team/assignee scope and payload/semantic deduplication.
  Signed fixtures and controlled real workspace tickets passed; see the later live evidence below.
- Real Anthropic structured generation for planner, builder and fresh reviewer; OpenAI Responses
  wire contract tested using a mock transport. No cached success is treated as a new paid call.
- Pinned Git snapshots and safe text-file edits; path/secret/sensitive-code rejection, original-test
  protection, conservative Python import impact analysis and mandatory full approved suite.
- Ephemeral non-root Linux Docker jobs without networking, credentials, host mounts or daemon socket;
  read-only root, bounded tmpfs, CPU/memory/PID/output limits, timeout and cleanup.
  Actual Docker tests cover memory, PID and disk exhaustion plus hostile PEP 517 dependency hooks.
- Independent baseline/candidate and criterion-specific pytest execution through an image-owned
  structured collector. The gate requires complete session/return markers, collected identities,
  setup/call/teardown phases, minimum counts and snapshot/command bindings; stdout summaries do not
  establish success. Strict candidate-manifest admission validates referenced artifact bytes and
  input/configuration/approved-plan/candidate/check/reviewer relationships before publication.
  Candidate code shares the collector interpreter: this closes named forgery/early-exit cases,
  not arbitrary semantic manipulation or inadequate tests. Independent behavioral oracles remain required.
- GitHub App publisher with repository-scoped installation token, base/head checks, draft-only PRs,
  operation markers/reconciliation and token revocation. Live App publication is verified by PER-13;
  broader provider fault qualification remains separate.
  A final PR reread checks exact base/head revisions, repositories, branch references, open state
  and draft status before recording publication success.
- GitHub signed observation endpoint and separate stale/merged/closed publication record;
  Linear read/status adapter. Signed check-run/check-suite observations durably invalidate readiness.
  The [CI gate](ci-evidence.md) binds numeric repository/head/producer/check identity, requires bounded
  authenticated REST reconciliation with matching complete snapshots and suite state, and uses
  generation CAS plus a 60-second cache. Workflow CI polling has an absolute deadline and cancellation.
  Linear review-state handoff is a separate activity after CI, with before/after authorization checks
  and intent/result artifacts; uncertain provider outcomes remain UNKNOWN. These are controlled
  transport/workflow tests, supplemented by the actual PER-13 App/CI/Linear handoff above.
- Evaluation schema, family/split validation, protected worker-input projection, isolated scoring,
  strict denominators, missing-task accounting and Wilson intervals. `delivery-eval` exports schemas,
  validates manifests and creates reproducible reports; no historical benchmark run exists.
  [Curation preparation](evaluation-curation.md) now contains 36 pinned metadata candidates, all
  UNQUALIFIED, zero qualified/scored; proposed groups do not constitute frozen eligible splits.
  [ADR-007](adr/ADR-007-automated-benchmark-qualification.md) replaces human benchmark curator/scorer
  prerequisites with isolated agent passes and deterministic qualification. The integrated v2
  controller and current admission authority now connect the executed stages; export, scoring and
  campaign preparation require this authority. Legacy qualification/campaign records allow only
  explicit inspection. The offline CLI has no trusted authority loader and refuses current admission.
  `human_minutes` is nullable; reported human-time savings remain null. Two separately acquired
  historical development tasks are qualified; the original 36 remain unqualified. No historical
  scoring or campaign has run, and human effort/benefit remains unmeasured.
- Pinned Compose development PostgreSQL/Temporal services, local CLI/API/worker entry points,
  tests and GitHub Actions quality/integration jobs.
- `/readyz` checks database readiness; authenticated `/operations` exposes repository-scoped
  workflow states, spending, and pending/exhausted dispatch summaries.

The offline evaluation CLI exposes [paired comparison](evaluation-comparison.md); the current
[campaign preregistration API](evaluation-campaign.md) requires concrete admission authority.
These preserve missing-task denominators, unmeasured human benefit, phase ordering and matched
budgets; neither executes a campaign.
The standalone [coverage importer/ranker](coverage-contexts.md) binds hints to exact measurement
inputs and always requires full regression execution. Its real coverage JSON smoke uses synthetic
local code and does not establish a qualified historical measurement or C-arm result.
Scoring now preserves original tests/configuration and revalidates the frozen collection and
receipt bindings; contradictory success/regression records fail validation.

[Validation-only qualification preparation](qualification-preparation.md) now checks pinned
controller/evidence/configuration bindings, exact reference-patch application and disjoint scopes.
Its offline CLI exports only PREPARED_NOT_QUALIFIED metadata. The [separate evaluation ledger](evaluation-execution-store.md)
and [bound model-operation receipts](model-operation-receipts.md) provide durable per-call
accounting/provenance and retain immutable failure observations without manufacturing delivery
workflows. A real bounded synthetic provider probe did not settle: 14465 microdollars remain
reserved, actual cost/cause unknown, no retry. These support the integrated qualifier; the campaign
execution controller remains missing. None of the 36 historical candidates has been admitted.

[ADR-010](adr/ADR-010-executable-qualification-stages.md) adds independently exercised stages:
[deterministic qualification runtime](qualification-runtime.md) runs actual preflight and twelve
clean checks with measured infrastructure accounting; [protected v2 review](qualification-v2.md)
provides inspectable source/oracle evidence and sealed-output adjudication; [development calibration](evaluation-calibration.md)
binds frozen cases to actual model-broker executions and recomputed metrics. Controlled transports
exercise model stages; paid owned-case calibration and two historical development admissions
are recorded below. Infrastructure
operations use zero model tokens and share an account ceiling with model calls. Individual stage
results remain non-admitting; current consumption requires the complete integrated chain.

[ADR-011](adr/ADR-011-current-qualification-authority.md) connects those stages through the
[private controller](qualification-controller.md) and [admission authority](qualification-admission.md).
The reader verifies actual execution chronology, sealed independent reviews, exact closed-account
receipts and current action-specific use permission. Synthetic validation cannot authorize historical
consumption. [Scoring execution](scoring-execution.md) separately authorizes and meters preflight,
acceptance and regression, with current authority checks and unknown-operation retry refusal.
The actual Docker integration exercises the full qualification, source-only export, metered score
and cached resume using controlled model responses and synthetic task records. This is software
verification, not live calibration or qualification of a historical candidate.

An earlier complete local verification on 2026-09-28 passed **1414 tests, seven explicit Windows
skips**, in 663.44 seconds with actual PostgreSQL, Temporal and Docker. The skips cover four POSIX
FIFO regressions and three unprivileged symlink cases; Linux CI exercises those platform cases.
Ruff check/format (215 files), mypy (75 source files), locked dependency validation, wheel build
and installed-wheel imports passed. The staged secret scan and
253 local links across 64 Markdown documents passed. Qualification/calibration tests use explicitly
synthetic agent/rights records and controlled model transports; they do not admit historical tasks.
Ten subsequent paid development calibration calls across two stages are recorded below; no historical benchmark ran.
The earlier unresolved probe remains unchanged.
The preceding complete checkpoint passed 1324 tests with seven Windows skips; all four hosted checks
passed on [c3d640c](https://github.com/ahines99/agentic-delivery-os/actions/runs/36469053647), including
1366 passing tests per Python version and 56 real-service integration tests. Counts from separate
full runs are not additive evidence.

The earlier complete local verification passed **163 tests** with `TEST_DATABASE_URL`,
`TEST_TEMPORAL_ADDRESS` and `TEST_SANDBOX_IMAGE` configured against actual Compose PostgreSQL,
Temporal and Docker. [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293)
passed all four checks on `d3fa44e`: Python 3.12, Python 3.13, PostgreSQL/Temporal/Docker,
and secret scanning. Packaging, clean wheel installation/migrations, Ruff, mypy and actionlint passed.
The [draft implementation PR](https://github.com/ahines99/agentic-delivery-os/pull/1) remains open for human review.

On 2026-09-28 a new complete local run passed **392 tests, zero skips**, in 107.40 seconds
with actual PostgreSQL, Temporal and Docker configured; Ruff check, format (116 files) and mypy
(52 source files) passed. A subsequent focused run passed 17 tests: 10 dispatch-scope and 7 actual Temporal CI/Linear tests,
including confirmed and UNKNOWN tracker outcomes, with 12 new tests overall. The collection
was 405 at that checkpoint after an additional real PostgreSQL CI concurrency test passed (two focused PostgreSQL tests). No full 405-test local run was claimed at that checkpoint. The rebuilt wheel installed in an isolated environment
and applied packaged migration 0006. These are working-tree results, not a new hosted CI result.
Scoped runs included 27 collector tests (9 actual Docker), 39 existing collector regressions,
70 manifest unit/adapter tests plus one actual Docker producer fixture, 113 CI contract/API/storage
tests, 14 handoff activity tests and 5 actual Temporal CI workflow tests. These scopes overlap;
do not add them to the full-suite count. The collector image exercised was
`sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8`.

A [closed-projection recovery drill](projection-recovery.md) passed 11 tests with actual local
PostgreSQL/Temporal: preview, repair from completed history, race/conflict refusal and idempotence.
It preserved spending/publication records and does not establish active-candidate or whole-system recovery.

A [local backup/restore drill](local-backup.md) restored a real PostgreSQL dump into a new disposable
database with matching ten-table counts and Alembic revision, verified 26 artifact digests, and
removed only that disposable database. A fresh 2026-09-28 drill restored migration 0006, matched
12 table counts, verified 46 artifacts (140503 bytes), and removed its disposable database; the
109106-byte dump has SHA-256 `f6c1fc64c7450887119f512833896aee8229de3d74d8836942adce45c2bcd234`.
These drills do not establish Temporal/provider recovery.

Further scoped operational evidence on 2026-09-28:

- [Active cancellation](active-cancellation.md): three real PostgreSQL/Temporal/Docker drills
  passed in 43.52s. Authorized cancellation stopped an observed parent/child workload and reached
  durable CANCELLED with no labelled containers in 15.359s. A failed cleanup acknowledgement,
  injected after real removal, reached FAILED in 15.312s; injected approval expiry reached FAILED
  in 4.265s. All histories replayed; no model/provider calls or spend. These controlled faults
  do not establish host-loss recovery, paid-model interruption or a general 30-second SLA.
- Active authorization (19 tests), pipeline guards (12) and [saved replay](versioned-replay.md)
  (7) passed together: 38 tests in 7.53s. Three saved histories from pinned commit
  `21077431f5839fd17d1ac2581dd16f13c04b567a` use synthetic activities/protocol data and replay
  against current workflow code, with a nondeterminism negative control. This is a prior-commit
  regression corpus, not a supervised deployment upgrade or activity/migration compatibility proof.
- [Operator rotation](operator-rotation.md): one PostgreSQL-backed real loopback HTTP test passed
  in 1.79s. Replacing temporary synthetic settings alone did not rotate the running API; orderly
  restart denied the old token and allowed the new scoped token. Paused admission and cancellation
  enqueue were checked; the cancellation remained RECEIVED without a worker. No actual token
  was rotated, and replica-wide/provider-key rotation and ingress TLS are outside this result.
- [Read-only retention](artifact-retention.md): 31 tests passed, two Windows cases explicitly
  skipped. A disposable PostgreSQL drill verified read-only/repeatable-read snapshots, retained
  DB/transitive references, classified an old unrelated file for review, and preserved workflow
  and artifact bytes. Only its newly created database was dropped and checked absent. The planner
  requires dedicated-store/quiescence/external-root/backup assertions and hashes the bounded
  inventory; it never authorizes or performs deletion. Ruff/format and targeted mypy passed.

These counts overlap existing scopes and remain separate from historical full-suite results.
The complete 1414-test verification above includes these changes. Scoped counts are not additive.

## Recorded live development runs

[Live development calibration](evaluation-calibration.md#revised-prompt-passing-development-calibration)
now passes all five original development cases with complete evidence and unchanged expected
findings. The revised prompt cost $0.760480; the earlier failed stage and its $0.735425 cost
remain retained. Both cached resumes added no calls or spending. This small reused development
set does not measure historical benchmark performance or admit any catalog task.

The owned synthetic calibration bootstrap now has typed project-owned provenance, a protected
five-case importer, runtime-verified review-input materialization and inert review subjects.
Its bounded preparation runner executes only safe anchors and makes no model calls. Known
reference/expected-answer aggregates cannot become review supporting documents or a rubric.
Request forecasts use the broker's actual serialization and reservation rules without network
access or spending. These capabilities are covered by controlled tests; actual preparation and
model calibration results are recorded separately below. They do not qualify any
of the 36 historical catalog candidates. See [ADR-012](adr/ADR-012-owned-synthetic-calibration.md).

These used the controlled synthetic customer fixture, not historical benchmark tasks. Credentials
were loaded from an explicitly authorized sibling project environment and never written to source.
Model spend comes from returned usage and the recorded rate card; it excludes infrastructure and
human effort. It is not a comparative performance claim.

| Run | Observed result | Model spend |
| --- | --- | --- |
| `4d89ec2c-d5d2-4a2d-b107-0864750d447c` | Durable live plan reached `PLAN_REVIEW`, then explicitly cancelled | $0.041415 |
| `81e980f4-7b25-4b1b-b964-322f2a28d748` | Local real build, new tests, verification, independent review; one attempt | $0.174500 |
| `79d5113b-2be7-462a-8179-260d832ccf9b` | Authenticated intake and approval through Temporal to a verified local candidate; stopped `POLICY_BLOCKED` at disabled publication | $0.184400 |
| `b3909403-fead-4093-ae60-c7d20cd3f181` | Real Compose-backed synthetic intake/approval/build/review; one attempt, `LOCAL_REVIEW_READY`, workflow `POLICY_BLOCKED` at disabled publication | $0.197655 |
| `d804b991-532d-4536-bfe4-bc7c5c4a02ff` | Earlier live Compose run with original-input/configuration/approved-plan bindings; one verified attempt, publication disabled | $0.192025 |
| `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322` | Fresh structured-collector Compose run, one attempt; strict manifest reference-chain validation passed, candidate `LOCAL_REVIEW_READY`, workflow `POLICY_BLOCKED` at disabled publication | $0.186240 |

The latest candidate's manifest is `16831b037bbe2afb4eb17cba179c71ae7691bce2ae1fe6c9f1e2fe820d16c98a`.
The exact live configuration and complete referenced evidence chain (three candidate files) were
validated; the local result is `.local/live-evidence-validation.json`. An earlier attempt in this
follow-up remained NEW before a model call when a 20-row unscoped outbox batch starved its command;
the development driver now dispatches its own workflow explicitly. This failure is retained as
operational evidence, not omitted from the development account.
Raw artifacts stay under ignored `.local/artifacts`; no sensitive artifacts are published by default.
The successful candidate result is `LOCAL_REVIEW_READY`, not a merged or deployed outcome.

## Remaining release gates

The complete owned-fixture qualification path has now passed with the larger-output
calibrated configuration: 13 actual Docker operations, two agreeing independent model
reviews and successful authority reconstruction for synthetic validation. Model cost
was $0.363880 plus 26 microdollars of infrastructure estimates, with zero reservation.
Cached recovery added no effects. Synthetic classification continued to deny admission,
worker export, scoring and campaign use. See the [completed qualification record](evaluation-calibration.md#completed-synthetic-qualification).

The revised qualifier prompt passed all five original development calibration cases
with complete evidence, at $0.760480 in configured model cost. The earlier failed
calibration remains retained; neither run measures held-out benchmark accuracy. A
subsequent synthetic qualification completed 13 Docker operations, then stopped when
its first model review hit the 5,000-token output limit. Its 234,400-microdollar
reservation was subsequently reconciled to $0.168415 of configured-rate model usage
through a distinct failed-call receipt, leaving no reservation for that operation.
No second review, adjudication, qualified task or campaign followed. See the
[calibration execution record](evaluation-calibration.md#subsequent-qualification-stopped-at-a-truncated-review).

The [offline historical importer](historical-import.md) now validates complete source
inventories and exact acquisition/provenance bindings for already acquired protected
bundles. It preserves original bytes and runs current preparation checks before
freezing metadata. Those synthetic tests imported no catalog candidate. Subsequent protected
acquisition and historical qualification are recorded below; campaign execution remains open.

A subsequent [protected public baseline acquisition](historical-acquisition.md#recorded-public-baseline-acquisition)
captured one replacement lead: 43 cachetools files, 230,124 source bytes, with complete
tree/blob verification and no code execution or model call. This advances baseline
acquisition only. It does not supply the requirements, rights, accepted reference or
oracle necessary for historical import and qualification.

The subsequent [issue requirements capture](historical-requirements.md#recorded-protected-capture)
stored the candidate's exact body privately after two matching provider-history
observations. Three read-only queries transferred 7,403 bytes; no model or repository
code ran. The current title remains historically unverified. Protected
[license observations](historical-input-provenance.md#recorded-protected-license-observations)
also bind the MIT text and provider-reported earlier license change. These records
do not themselves authorize processing or admit a historical task.

Verified donor reuse then captured the complete accepted commit in five snapshot
reads plus one parent-link check. Its 43 files/231,483 bytes remain protected
reference evidence. A private static check found three added test candidates;
collection and actual behavior remain unvalidated. The subsequent protected derivation
refused that lead's test-filename shape. The refusal is retained without broadening
the profile to admit it.

[Source-layout execution](src-layout-verification.md) and standalone
[reference derivation](historical-reference-derivation.md) are now implemented and
tested with owned fixtures. A later metadata screen identified two potentially eligible
development leads among twelve examined; the first, schedule PR 463, passed protected
derivation with two frozen acceptance selectors. The explicit v2 importer and
[derived qualification-input path](derived-qualification-inputs.md) now bind the
captured requirements, both current data authorizations and protected reference exclusions.
Owned controller tests cover both outer checkpoints, current admission, resume and
shorter-grant expiry. The first lead subsequently received finite data authorizations
and reached actual v2 import and runtime. Its [recorded attempts](historical-development-attempts.md)
retained a missing dependency, then stopped after the corrected environment collected
both frozen acceptance nodes and observed one passing on the baseline. The protocol
requires both to fail. No reference run or model review followed for that candidate.
The second lead, PR 404 / issue 304, passed all thirteen deterministic operations:
three acceptance nodes discriminated baseline/reference and 26 original regressions
passed on both variants, each across three repetitions. Its first model review hit
the 8,000 output-token limit; exact usage reconciliation settled 540,575 model
microdollars plus 26 infrastructure microdollars, with zero remaining reservation.
No valid review or admission resulted from that attempt. After separate calibration of
a larger output allowance on unchanged owned fixtures, a fresh attempt passed all
thirteen deterministic operations and two agreeing independent reviews. Current
authority validation admitted PR 404 as one historical development task. Its successful
attempt cost 1,165,501 microdollars including estimated infrastructure, with zero
reservation; all earlier failures remain retained. No historical task has been scored
or used in a campaign. A third development lead, PR 337 / issue 331, subsequently
passed all thirteen deterministic operations and two agreeing independent reviews,
with current authority validation: two development tasks are now qualified. Its
successful attempt cost 1,004,951 microdollars including estimated infrastructure,
with zero reservation; earlier acquisition and import setup refusals remain recorded.

Two [actual failing-baseline checks](baseline-failure.md) now preserve assertion and
collection failures while proving the delivery pipeline makes no model call,
reservation or candidate. They exercise Docker and the production verifier, with
all four created containers removed. A subsequent actual PostgreSQL/Temporal/Docker and
loopback-HTTP test proves durable failure routing to authenticated operator detail,
worklist and audit views, with receipt preservation and workflow-history replay. This
uses an automated test-role approval; human observation and live Linear routing remain
unmeasured.

1. The installed App, protected target and actual publication now pass the bounded live
   demonstration. Extend provider lost-response/head-change reconciliation qualification
   and onboard each additional repository explicitly. The product never uses the CLI token.
2. Automatic Linear detection and the real PR-link/In Review handoff are verified by
   PER-13. The supervised local login service is running. Always-on hosted operation and
   signed external merge/close callbacks remain separate work.
3. Extend security qualification beyond the exercised memory/PID/disk/dependency-hook controls.
   Current Docker tests do not establish general runtime-escape resistance or hostile multi-tenant isolation.
4. Extend fault qualification beyond the successful live App REST readiness gate.
   Complete granular active-execution crash recovery, production identity hardening, full telemetry,
   coordinated deletion and cross-system recovery. Active cancellation, saved replay, local token
   rotation and read-only retention plans do not replace these broader operational gates.
5. Independently qualify 30+ historical tasks from a reviewed inventory, then execute the frozen paired evaluation
   with calibrated independent agent scoring and authoritative deterministic tests under ADR-007.
   Manifest validation and one owned live demo cannot satisfy this requirement. Plan
   approval follows ADR-025; pilot signoff and merge remain human controls.
6. Meet the complete product P-01–P-12 and security acceptance gates before calling this an MVP pilot.
   Additional trackers/languages/profiles and release automation remain conditional future options.

Use [ADR-006](adr/ADR-006-verified-local-candidate.md) for the deliberate prepublication review
and draft-handoff refinement. This repository is an implemented controlled prototype, not a claim
of a completed production delivery platform.

See [provider onboarding](provider-onboarding.md) for the exact GitHub App and Linear inputs.
This project's protected `main` requires green CI and one approving review, including administrator
enforcement; force pushes and automatic merge are disabled. Product target repositories need
their own protections and live onboarding evidence.

The [completion audit](completion-audit.md) retains all 29 backlog items, 12 product gates and
36 research recommendations, including the remaining acceptance and external prerequisites.

A bounded [operational metadata export](operations-export.md) was exercised against actual private
PostgreSQL for workflow `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322`; output SHA-256
`cac7f2b60b5a8def617cbb15939829cf920c82717347005a5472355241758ef6`.
It contains allowlisted metadata, not artifact bytes or secrets. This advances M4-03 only within
that scope; coordinated retention/deletion, a full telemetry service and cross-system recovery
remain open despite the separate bounded read-only retention planner.


## Prospective protocol decision

[ADR-016](adr/ADR-016-prospective-campaign-token-ceilings.md) accepts an explicitly
selected 500,000-input/64,000-output protocol while retaining all financial, time,
corpus and promotion limits. [Contracts and current consumers](protocol-v2-implementation.md)
are implemented and independently reviewed; historical activation remains gated. Existing
v1 types, grants, costs and frozen records are unchanged; the decision supplies no
calibration or execution authority.


The subsequent hosted run at `c9b8b03` retained three storage-isolation test failures
on each Python version (2353 passed, 87 skipped); service integration passed 87 cases.
The new concrete-authority check preceded the existing store-overlap refusal in these
unit fixtures. The overlap guard now rejects before qualification reads, and the
strengthened tests prohibit those reads. Independent review cleared the reorder;
137 affected tests passed with one optional Docker skip. A further integrated v2
protocol/protection/qualification scope passed 138 tests with one integration case
deselected. New-head hosted verification is still required; these counts overlap.

The v3 independent-finding prompt preserved v1/v2 bytes, schemas and expectations.
Its separately authorized Opus 5 calibration again completed five valid outputs and
five overall verdict matches, but four exact finding maps and one mandatory failure.
It settled 574,790 microdollars with no reservation. Final scoring remains gated.


The separate Opus 5.5/v3 final-scorer profile subsequently passed all five exact owned
anchors (365,540 microdollars, no reservation), including current read-only passing
validation. This supersedes the absence of any passing configuration, not earlier
failed records. It supplies neither held-out accuracy nor historical spending authority.

The subsequent [hosted run at `700fc45`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36506867142)
retains one Python 3.12 test failure (2464 passed, 88 skipped, 730.82 seconds), and Python
3.13 exceeded the 15-minute job limit. Service integration passed 88 cases in 251.50 seconds;
secret scanning passed. The CLI denial fixture incorrectly reused its protected store as
output storage, so the earlier isolation check correctly rejected first. The fixture now
uses disjoint stores and forbids all artifact reads; 104 CLI/qualification tests passed with
one optional Docker skip. The growing full-suite job receives 30 minutes, with no tests or
runtime execution deadlines removed. New-head full verification remains required.

[Explicit merge linkage](historical-merge-linkage.md) implements
[ADR-017](adr/ADR-017-explicit-first-parent-merge-linkage.md), preserving v1 while admitting
only structurally valid first-parent/two-parent metadata under an explicit new profile.
Owned tests and independent review passed; no historical admission follows from those tests.

The [single-attempt coordinator](single-attempt-coordinator.md) composes allocation, A/B
candidate production, deterministic checks and two initial semantic scorers on one account
and deadline. Controlled composition/recovery tests and independent review passed. It does
not yet schedule phases or adjudicate disagreements, and no historical campaign was run.

The shared v2 adjudication prompt passed five focused broker/version tests. Its first live
owned calibration request returned HTTP 400 before usable evidence; a separate schema-only
diagnostic identified unsupported `prefixItems` in the provider-facing fixed-tuple schema.
Both reservations remain retained because no usage was reported. That calibration attempt
did not pass; the later prospective run after the wire correction is recorded below.

Linear's owner-supplied personal key now passes actual read-only workspace/team/member/state
discovery through the product adapter. Local configuration pins the matching team, active
assignee and In Review state. Those discovery reads alone establish no delivery or handoff;
subsequent signed delivery is recorded below. GitHub App onboarding remains open.

After the narrow homogeneous fixed-tuple projection, a separately frozen live owned
adjudicator calibration passed all five exact dispute maps and verdicts, with no false-ready,
mandatory failure or new concern. Five calls settled for 380,444 microdollars with zero
reservation; cached recovery and required-pass readback with writes forbidden succeeded.
The [full record](semantic-adjudication-calibration.md#recorded-live-owned-calibration)
retains the earlier HTTP failures and their unknown reservations. Historical adjudication,
corpus qualification and phase execution still need their separate authority and evidence.

The historical adjudication executor is now implemented and independently reviewed, with
current calibration consumed successfully and controlled exact-tail/recovery tests passing.
It has not adjudicated a historical task. Its separate result still needs downstream campaign
composition and phase reporting.

Actual Linear signed intake is now exercised through the narrow temporary HTTPS gateway:
controlled ticket PER-5 created one durable workflow/start command. A real non-content update
and exact signed replay preserved that single workflow and budget. Private routes and unsigned
requests were rejected externally. These checks do not establish durable hosting or live
GitHub/Linear review-state handoff; see [the detailed evidence](linear-ingress.md).

The two controlled real tickets then exercised actual planning on separate, narrowly dispatched
Temporal queues. PER-5 reached `NEEDS_CLARIFICATION` (one settled call, 85,630 microdollars);
PER-6 reached `PLAN_REVIEW` (one settled call, 64,855 microdollars), with five criteria and no
clarification questions. Both retained zero reserved balance and their original workflow/budget
identities. Private plan artifacts remain local. Both workers stopped at these boundaries;
no plan approval, candidate execution, publication or Linear review-state update occurred.
