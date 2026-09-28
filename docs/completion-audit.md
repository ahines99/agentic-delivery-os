# Full-scope completion audit

Audit date: 2026-09-28. Initial inspected checkout: `16dd9fe9e873225dbaee0f761971efcf902e8b72`; the dated follow-up below includes subsequent working-tree implementation and scoped execution evidence, not a newly certified release SHA. This is a completion ledger for the accepted M0–M5 plan, the twelve product gates, and the five research reviews. It does not replace or reduce their acceptance criteria. Subsequent implementation needs new evidence and an updated ledger.

**Finding: the five-agent planning/research baseline and a substantial controlled implementation exist. The complete MVP and portfolio release are not proved.** Live Linear-to-GitHub handoff, full operational/security qualification, a qualified historical corpus, paired execution and independent agent scoring under ADR-007 remain open. The project's manually maintained implementation PR is not a product-generated delivery PR.

## Meaning of status

| Status | Meaning |
| --- | --- |
| proved | Concrete inspected evidence satisfies the specifically named scope; does not imply adjacent capabilities. |
| partial | Implementation or bounded tests exist, but at least one required part or proof is absent. |
| missing | No implementation or qualifying result was found in the inspected sources/artifacts. |
| external prerequisite | Completion requires authorized account/environment access or actual human judgment; local mock fixtures cannot substitute. |
| deferred-by-plan | Explicitly excluded from M0–M5 by the accepted plan; not used to relabel unfinished required work. |

A parent item stays open when any required part is partial, missing or externally blocked. Code presence is not execution proof; signed synthetic payloads are not live provider onboarding; two reviewer names in JSON are not two independently executed, provenance-bound agent decisions. A digest proves byte identity, not the truth of the artifact's claims.

## Evidence inspected

| Ref | Concrete evidence and boundary |
| --- | --- |
| E1 | [Plan](plan.md), [backlog](backlog.md), [product contract](product-spec.md), [architecture](architecture.md), [security](security-model.md), [evaluation protocol](evaluation-methodology.md), five linked research reviews and ADR-001 through ADR-006. These establish decisions, not passed execution gates. |
| E2 | `domain/models.py`, `domain/lifecycle.py`, `policy/engine.py`; `tests/test_foundation.py` covers strict risk values, missing/stale evidence, illegal transitions and self-review rejection. Structural predicates only. Paths in this ledger are relative to `src/agentic_delivery/` unless prefixed otherwise. |
| E3 | `config.py`, `security.py`, `api/app.py`, `storage/{schema,store}.py`, migrations 0001–0004; `tests/test_control_plane.py` and `tests/test_postgres_integration.py`. Real PostgreSQL concurrency test covers intake and spend reservation; most API/command scenarios use local SQLite and test transports. |
| E4 | `orchestration/{workflow,activities,dispatcher}.py`; `tests/test_temporal_integration.py`. Real Temporal exercises worker restart during human wait, stale command, cancellation and history replay, but planner/candidate/publication activities in those tests are controlled fixtures. They are not live provider or in-flight real-builder recovery tests. |
| E5 | `integrations/model.py`, `agents/{contracts,pipeline}.py`; `tests/test_model_adapter.py`, `tests/test_pipeline.py`; retained live candidate manifest described below. Real Anthropic development activity is recorded; provider selection through a comparative development experiment is absent. |
| E6 | `execution/{docker,files,verification}.py`, `repository/snapshot.py`, `policy/changes.py`; `tests/test_execution.py`, `tests/test_snapshot.py`, `tests/test_sandbox_adversarial.py`. Actual Docker probes include denied egress, no broker canary, resource limits, read-only root and hostile PEP 517 hooks. This is a named-control suite on a controlled host, not general escape resistance. |
| E7 | `integrations/github.py`, `integrations/linear.py`, GitHub observation route/store, `tests/test_github_adapter.py`, `tests/test_linear_adapter.py`. Inspected tests use HTTP mock transports and fabricated provider records. Live product App publication and live Linear delivery were not found. |
| E8 | `evaluation/{harness,cli}.py`, `repository/impact.py`, `tests/test_evaluation*.py`, `evals/README.md`. The CLI exports schemas, validates JSONL and reports supplied trials; it does not execute a campaign. AST imports are implemented; later standalone coverage-context tooling is recorded at E23. |
| E9 | [Hosted CI run 36374850293](https://github.com/ahines99/agentic-delivery-os/actions/runs/36374850293), queried through authenticated read-only GitHub CLI on audit date: success at `d3fa44e4bce515760ea912431f4fe08f2899a481`; Python 3.12/3.13, real PostgreSQL/Temporal/Docker integration job and secret scan all passed. This is an earlier revision than this audit checkout and contains no real model/Linear/App secrets. It does not prove every P gate. |
| E10 | [Implementation PR #1](https://github.com/ahines99/agentic-delivery-os/pull/1), queried on audit date: open, draft, head `16dd9fe9e873225dbaee0f761971efcf902e8b72`. Read-only branch-protection query confirms four required checks, strict up-to-date requirement, one approval, stale-review dismissal, admin enforcement, and no force pushes/deletions on this project's `main`. Target repositories need their own checks. |
| E11 | `.local/live-delivery-result.json` and actual retained artifact `60c0d5f30afd7a55831da20c8f88ae5e783f3f6b4c22dda1ee1d8096434623e2`: bytes rehashed to that digest; run `d804b991-532d-4536-bfe4-bc7c5c4a02ff`, synthetic `demo/customer-service`, base `be84b17971ffbb8a6d944da8a601ba69e9b19fb9`, one attempt, passing baseline and model APPROVE. Candidate result is `LOCAL_REVIEW_READY`; publication was disabled. Metadata inspected without printing source/secrets. This audit did not rerun a paid model call. |
| E12 | `scripts/backup_local.py`, `tests/test_backup.py`, [backup drill](local-backup.md), retained `.local/backups/20260928T034856Z-c229c0cc832c4234b7114ce5d1b688fa/manifest.json` inspected with status `VERIFIED_LOCAL_DRILL`. The earlier drill used revision 0004. A fresh actual drill at `.local/backups/20260928T141014Z-e811f547a5fa46a196dc1f48bfc51916/` restored revision 0006, matched 12 table counts, verified 46 artifacts (140503 bytes), and removed the disposable database. Dump: 109106 bytes, SHA-256 `f6c1fc64c7450887119f512833896aee8229de3d74d8836942adce45c2bcd234`. Neither drill resumes a workflow or proves row-by-row/cross-system recovery. |

Dated follow-up evidence (2026-09-28) records bounded work after the initial audit:

| Ref | Concrete evidence and boundary |
| --- | --- |
| E13 | Approval expiry/current reviewer authority at use; `infra/docker/collector.py`, `execution/verification.py` and strict `agents/evidence.py` admission. Collector image `sha256:e53c321ff35f72cce9a52ceb147a15410e20b39ecc820144b975b9e5c2a5d7c8`: 27 new collector tests (9 actual Docker), 39 existing regressions; strict-manifest scope 70 unit/adapter tests plus 1 actual Docker producer-fixture test. Counts are separate scoped runs, not additive coverage. Report bindings/hashes do not attest arbitrary code in the same interpreter. |
| E14 | [CI contract](ci-evidence.md), check-run/check-suite signed observation persistence, migrations 0005/0006, generation CAS and 60-second snapshots; read-only App broker validates exact PR context and complete producer-scoped checks/suites. Two matching bounded paginated check-run snapshots and suite checks surround reconciliation. Workflow polls to an absolute deadline, supports cancellation, and performs Linear handoff separately with before/after gates and intent/result artifacts (UNKNOWN on uncertain outcomes). 113 CI contract/API/storage tests; 14 handoff activity tests; 5 actual Temporal CI workflow tests recorded as scoped runs. These use controlled provider responses, not live product App/Linear authorization. |
| E15 | Fresh synthetic workflow `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322`: one attempt, `LOCAL_REVIEW_READY`, durable `POLICY_BLOCKED` because publication was disabled, model spend $0.186240. Manifest `16831b037bbe2afb4eb17cba179c71ae7691bce2ae1fe6c9f1e2fe820d16c98a`; the strict validator reconstructed the exact live configuration and validated its complete reference chain (three candidate files), retained in ignored `.local/live-evidence-validation.json`. An earlier attempt in this follow-up stopped at NEW before a model call because an unscoped 20-row outbox batch was starved; scoped development dispatch was added before this successful rerun. Not a historical task or product handoff. |
| E16 | [Projection recovery](projection-recovery.md): 11 tests passed against actual local Compose PostgreSQL/Temporal, including deliberate damage of only a unique synthetic closed workflow projection, preview, history-bound repair/CAS and idempotent repeat. Spending/publication records stayed unchanged. This neither resumes real candidate activity nor establishes full-system recovery. |
| E17 | [Evaluation curation](evaluation-curation.md): 36 real metadata candidates, all UNQUALIFIED, zero qualified/scored tasks. Pinned upstream revision/base and license provenance, metadata-only export and offline validation/worklist exist; proposed groups are not a frozen qualified corpus. Rights/issue linkage, actual independent agent qualification, stable oracles and campaign execution remain open. ADR-007 supersedes the former human-curator prerequisite without admitting any candidate. |

| Ref | Further 2026-09-28 follow-up and boundary |
| --- | --- |
| E18 | [ADR-007](adr/ADR-007-automated-benchmark-qualification.md) records the user's explicit hands-off benchmark preference. `evaluation/qualification.py` implements bounded offline validation of dual-agent provenance and deterministic qualification receipts; `validate-qualification` checks all task records against protected artifacts; worker-input export and candidate scoring refuse unverified structural manifests before reading snapshots or starting Docker. Local qualification unit and real Docker receipt checks pass; the integrated qualifier admission controller remains missing. A supplied digest or agent name is not authenticated execution. No actual candidate admission or campaign is claimed; all 36 remain UNQUALIFIED. |
| E19 | [Operational export](operations-export.md): actual private PostgreSQL export for workflow `2abb68f2-d32f-4ceb-90e9-5b8f53e9b322`, output SHA-256 `cac7f2b60b5a8def617cbb15939829cf920c82717347005a5472355241758ef6`. Allowlisted correlation/spend/state metadata only; no artifact bytes or secrets. This bounded snapshot is partial M4-03 evidence, not retention/deletion, a metrics service, whole-system recovery or complete telemetry. |

The **163-test** local run remains historical baseline evidence. A follow-up full local suite passed **392 tests, zero skips**, in 107.40 seconds with actual PostgreSQL/Temporal/Docker; Ruff check/format (116 files) and mypy (52 source files) also passed. A subsequent focused run passed 17 tests (10 dispatch-scope and 7 actual Temporal CI/Linear tests, including confirmed and UNKNOWN tracker outcomes); it includes 12 newly added tests. Two focused PostgreSQL tests then passed, including a new concurrent CI inbox/reconciliation-generation test. The collection at that checkpoint was 405, without a complete 405-test local run claimed. A rebuilt wheel installed in an isolated environment and applied packaged migration 0006 successfully. These are dated working-tree results, not a final hosted release revision. Scoped counts above overlap and must not be summed. Earlier hosted CI proves its recorded SHA only. Do not combine historical CI, current source and synthetic demonstrations into one complete production run.

E20: [Paired comparison tooling](evaluation-comparison.md) now provides seeded paired bootstrap,
Wilson intervals, explicit missing-task/cost coverage, discordant pairs and an offline `compare`
CLI. Synthetic arithmetic tests pass; results do not authenticate scoring or imply a campaign.

E21: [Automated curation feasibility](research/06-automated-curation-feasibility.md) records primary
source rights/runtime findings. [Current issue-link metadata](../evals/candidates/issue-links.json)
contains associations for 17/36 candidates without issue bodies or answers. Exact historical
environments remain unqualified, including the pytest collector/target runtime conflict.

E22: [Campaign preregistration](evaluation-campaign.md) validates qualified task records, unique
historical issues, equal splits, arm parity, a stratified stability subset, phase-ordered seeded
scheduling and worst-case cost. Tests include CLI boundaries. Output explicitly denies spending
authority and marks calibration unverified; it does not implement a campaign executor.

E23: [Coverage context tooling](coverage-contexts.md) imports digest/revision/configuration-bound
line contexts, retains unknowns and ranks tests while always requiring the full suite. An actual
coverage.py export on synthetic local code tests JSON compatibility only; the receipt's test
provenance is synthetic. No product integration, qualified repository measurement or C-arm run exists.

E24: Independent review found and fixed scorer acceptance of modified original tests/controls,
missing frozen collections and contradictory PASS/regression records. Scoring revalidates exact
collections and receipt bindings; actual Docker positive/negative synthetic scores pass. Shared
artifact and coverage readers reject nonregular files without blocking on POSIX FIFOs; Windows
cannot exercise that POSIX case and reports an explicit skip.

E25: [ADR-008](adr/ADR-008-active-authorization-and-cancellation.md) implements worker-side
current-configuration authorization, per-operation checks, a five-second candidate monitor,
cleanup exception propagation and `verified-cancellation-outcome-v1`. A scoped run passed
19 active-authorization, 12 pipeline-guard and 7 saved-replay tests together (38 tests, 7.53s).
[Three actual PostgreSQL/Temporal/Docker drills](active-cancellation.md) passed in 43.52s:
authorized active cancellation reached durable CANCELLED with no labelled containers in
15.359s; injected failed cleanup acknowledgement reached FAILED in 15.312s; injected approval
expiry reached FAILED in 4.265s. Each replayed history; no model/provider call or spend occurred.
The cleanup failure was injected after successful real removal, and expiry aged only its
synthetic approval. These are not daemon/host-loss, paid-model cancellation or universal SLA proofs.

E26: [Operator rotation rehearsal](operator-rotation.md) passed one real loopback HTTP test
with PostgreSQL in 1.79s. Temporary synthetic token/config replacement required orderly API
restart; old-token denial, new-token scoped reads, paused admission and authorized cancellation
enqueue were verified. The queued cancellation stayed RECEIVED without a worker. Actual
operator credentials were unchanged; no replica-wide, hot-reload or provider-key rotation claimed.

E27: [Saved replay corpus](versioned-replay.md) contains three actual Temporal histories
generated from pinned production commit `21077431f5839fd17d1ac2581dd16f13c04b567a` with fake
activities and synthetic protocol payloads. Seven offline tests include current-workflow replay,
hash/protocol checks and an incompatible-command negative control; they are included in E25's
38-test scoped run. This is a saved prior-commit regression corpus, not a supervised deployment
transition, pre-CI-patch corpus or proof of activity/database upgrade compatibility.

E28: [Read-only retention planner](artifact-retention.md) passed 38 focused tests with two
explicit Windows skips (symlink privilege, POSIX FIFO). An actual uniquely named disposable
PostgreSQL database verified both snapshots were read-only/repeatable-read, database/transitive
references stayed KEEP, one old unrelated file was CANDIDATE_REVIEW_ONLY, and workflow/artifact
bytes stayed unchanged. Only that created database was removed and its absence verified; shared
state was untouched. The bounded, hash-validating planner requires explicit dedicated-store,
quiescence, complete external roots/holds and independent-backup assertions; reports bind DB,
config and listing without raw payloads. Independent review reproduced and corrected missed nested
escaped references and duplicate-key ambiguity: bounded decoded-string traversal retains the former
and duplicate keys refuse planning. There is no deletion API or deletion authorization.
Ruff check/format and targeted mypy passed. The final complete local operational-update suite
passed 748 tests with five explicit Windows skips in 254.01s, including actual PostgreSQL,
Temporal and Docker. Ruff/format (154 files), mypy (59 source files), locked dependency validation,
wheel build/installation and staged secret scan passed. These overlapping scoped counts do not
replace or add to historical full-suite totals above; hosted CI must verify the final commit.

E29: [PostgreSQL transaction/outbox faults](postgres-faults.md) passed 12 cases against real
PostgreSQL and Temporal. Injected insert/precommit failures leave no partial intake/revision;
committed-response loss deduplicates; reclaimed leases fence the old owner. Three lost-start/ack
cases retain one Temporal run through redelivery, canonical cancellation and history replay.
Exceptions and scoped lease acceleration simulate boundaries; no process crash or partition is claimed.

E30: [Model-provider faults](model-provider-faults.md) passed five actual PostgreSQL ledger cases
with controlled HTTP transport: 429, 503, lost response and in-flight cancellation retain reservation
and deny duplicate logical calls; a committed settlement with lost acknowledgement returns cached
output. Fresh database engines verify persisted accounting. No external/paid call or actual invoice
reconciliation is claimed, and unknown reservations are not released automatically.

E31: [Model-operation receipts](model-operation-receipts.md) and [ADR-009](adr/ADR-009-model-provenance-and-evaluation-accounting.md)
add per-call reported tokens, configured-rate cost, response object identity, timestamps and
request/config/output bindings. Cache recovery checks the owning ledger and exact request before
returning output; legacy records gain no invented provenance. Immutable allowlisted observations
retain unsuccessful response/transport/cancellation metadata without releasing reservations.
Controlled transport tests cover both delivery and evaluation stores, malformed output and actual
Temporal error serialization. Hashes do not authenticate arbitrary writers or reconcile invoices.

E32: [Separate evaluation ledger](evaluation-execution-store.md) passed 35 scoped tests including
a unique disposable PostgreSQL database and concurrency. Model cost/token ceilings, unknown
retention, immutable observations/checkpoints and schema/foreign-key checks are separate from
delivery workflows. Accounts do not authorize spending; infrastructure, wall-time and total
campaign allocation still require the executor.

E33: [Qualification preparation](qualification-preparation.md) supplies strict imported evidence
and controller-policy bindings, scope separation and exact in-memory reference-patch application.
The pure API and offline CLI output PREPARED_NOT_QUALIFIED and no execution authority. A combined
preparation/CLI/ledger run passed 133 tests with two explicit Windows skips. Synthetic attestations
are not historical acceptance, source-origin proof or legal clearance. No task was admitted.

E34: An attempted real Anthropic synthetic receipt probe used a 100000-microdollar cap and ended
in ModelFailure. Account `synthetic-model-provenance-24346e68a8b9410e9431b21e36c750ef` retains 14465
reserved microdollars; its final actual cost and failure cause are unknown. No retry or successful
receipt is claimed. This occurred before diagnostic observations were added; absent HTTP metadata
was not fabricated. The private ledger remains outside the repository.

## M0–M5 backlog ledger

Every stable backlog ID appears below. Dependencies continue to apply even where later implementation was developed ahead of a milestone's full gate.

| ID | Status | Inspected evidence / remaining acceptance | Next action |
| --- | --- | --- | --- |
| M0-01 | proved — planning deliverables | E1: product, architecture, security, evaluation, ADRs and all five reviews exist; original handoff retained. Some historical wording needs synchronization, listed below. | Preserve the full acceptance baseline and resolve document drift without weakening gates. |
| M0-02 | proved — structural foundation | E2 and E9: contracts, explicit transitions, intake policy, stale/missing/self-authored evidence tests. Runtime authenticity is separately open. | Continue regressions; do not reuse this proof as M3 evidence provenance. |
| M0-03 | proved — foundation at recorded CI revision | Three fixtures, health route, package/lockfile, contribution assets and hosted checks exist (E2/E9). | Run the required checks again for the final changed revision; retain result SHA. |
| M1-01 | partial | E3: repository/provider/operator allowlists, command profiles, protected paths, finite model/token/wall limits and secret references. Full environment onboarding and infrastructure budget enforcement absent. | Validate complete connected settings before admission; add explicit infrastructure/transport budget contract and qualification record. |
| M1-02 | partial | E3/E29: real PG concurrency plus rollback, committed-response loss, reclaimed-lease fencing and actual Temporal redelivery at injected commit/dispatch/ack boundaries. Full process/database crash matrix remains open. | Extend to process loss, database failover and terminal-workflow races without conflating injected exceptions with crashes. |
| M1-03 | partial | E4/E16/E27: durable wait/restart/replay, actual closed projection repair, and three saved prior-commit synthetic histories replayed by current code. Full version-transition qualification and granular real-build recovery remain open. | Extend history branches and rehearse supervised upgrades, activity compatibility and active-execution crashes. |
| M1-04 | external prerequisite, with partial code | E3/E7: signature, timestamp, org/team/assignee checks, payload/semantic dedup; no live Linear organization or callback evidence. | Authorized workspace/team/worker/API+signing keys and HTTPS endpoint; exercise real delivery, duplicate, stale/out-of-order and changed-ticket handling. |
| M1-05 | partial | E5/E11: real Anthropic plans/build/review, strict response parsing and durable reservations. ADR-006 explicitly says account availability selected provider, not benchmark comparison. | Run and retain development selection experiment; strengthen malformed/429/timeout/cancellation and billed-usage reconciliation proof. |
| M1-06 | partial | E3/E4/E5: revised specifications, unchanged existing criteria, max observed risk, plan digest, authenticated clarification. Real synthetic plan exists; full live Linear clarification and adversarial missing-requirement cases absent. | Exercise ambiguity→authorized revision→new plan end to end, including stale/unauthorized answer and immutable source identity. |
| M1-07 | partial | E3/E4/E13/E16/E25/E26: canonical commands, worker current authorization/expiry monitoring, actual active Docker cancellation/expiry, cleanup-error classification and restart-based HTTP token rotation. Full recovery/identity qualification remains open. | Extend worker/daemon/host-loss, paid-operation uncertainty and multi-process credential/revocation scenarios. |
| M1-08 | partial preparation; agent qualification required | E8/E17: 36 metadata-only candidates are explicitly UNQUALIFIED; zero qualified or scored tasks. Rights/linkage decisions, independent agent judgments with immutable execution provenance, oracle qualification and final frozen splits remain open. | Use the curation worklist; execute two isolated agent reviews per task with disagreement handling and oracle stability/leakage evidence before promotion. |
| M2-01 | partial | E6/E9 prove actual named Docker resource, egress, filesystem and credential probes. Broader malicious runtime/cleanup/host-admission qualification remains open. | Extend adversarial cases on the selected host; document residual shared-kernel risk and fail release on unresolved bypasses. |
| M2-02 | partial | E6/E11: exact Git snapshot, fixed image, separated offline execution and real passing baseline. No general dependency bundle/lock qualification path for multiple historical repositories. | Add pinned dependency preparation/provenance and a failing-baseline integration case; retain installation/baseline records. |
| M2-03 | partial | E5/E6: typed edit proposal replaces arbitrary tools; policy and budget sit outside prompt. Real builder ran. Fault/authorization matrix and development provider qualification incomplete. | Exercise schema/rate-limit/cancel/errors and demonstrate no execution or spend following denied admission. |
| M2-04 | partial | E6/E11: safe paths, symlink rejection, original tests/protected configuration, exact old-content hashes, immutable candidate/diff artifacts. Complete hostile-output and candidate-reproduction matrix absent. | Verify candidate reproduction and add symlink/traversal/size/secret cases across the entire builder-to-publisher boundary. |
| M2-05 | partial | E6/E13: image-owned structured pytest collection replaces stdout verdicts; completion, identities/phases, minimum counts and execution bindings are checked. Named forged-summary/early-exit cases now have actual Docker tests. Candidate code still shares the collector interpreter. | Qualify malicious runtime/oracle cases and independent behavioral checks; do not treat structured reports as semantic attestation. |
| M3-01 | external prerequisite, with partial code | E7: scoped App token broker, branch/tree/PR markers, final exact-ref reread, no merge API; HTTP contract tests only. E10 is not a product App PR. | Install authorized least-permission App; exercise real draft creation, unknown response reconciliation, duplicate/head/base races, token revocation and no-bypass protection. |
| M3-02 | partial | E5/E11: fresh reviewer context and one real approving result; bounded correction loop exists. A real rejection→repair→new validation/review result not recorded. | Add controlled reviewer rejection/exhaustion tests and a live development rejection/repair run; maintain separate capabilities and shared budgets. |
| M3-03 | partial | E13/E14/E15: strict manifest/reference validation, structured collection and independent producer-scoped CI observations/reconciliation are implemented and fixture tested; fresh synthetic manifest passed the gate. Live App check evidence and complete manual pending/denial handling remain open. | Exercise the full onboarded product chain, manual evidence semantics and remaining adversarial provenance/race matrix. |
| M3-04 | external prerequisite, with partial code | E7: Linear state adapter and signed GitHub PR observations, staleness/merge/closed records. No actual Linear→product PR→observed close/merge run. ADR-006 keeps PR draft for human review. | Complete live integration sequence and preserve signed receipts and revision tuple; human performs readiness/merge. Do not infer deployment. |
| M3-05 | missing; qualified data/campaign prerequisite | No A/B development/validation campaign or promotion result found (E8). Synthetic success is outside the historical denominator. | Implement campaign executor and genuine A/B configuration, qualify tasks, run equal-cap arms with the frozen calibrated automated rubric; leave sealed split unopened. |
| M4-01 | partial | E3/E4/E7/E25/E27/E29/E30 cover fixture faults, wait restart, saved replay, actual active Docker cancellation below 30 seconds, PG rollback/redelivery and model reservation recovery. No actual candidate-worker crash or unknown live publication recovery drill. | Extend daemon/host/worker crashes, paid-model cancellation and actual-provider lost-response reconciliation; retain one-effect evidence. |
| M4-02 | partial ? release qualification open | E2/E6/E7/E13/E14: named forged-summary/early-exit paths now rejected; strict manifest and CI producer/revision/rerun guards have regressions. Complete prompt-injection, malicious oracle and race qualification remains open. | Execute the full P-03/P-06/P-09/P-11 matrix on the actual selected runtime; investigate same-interpreter evidence limitations. |
| M4-03 | partial | E3/E12/E16/E19/E26/E28: operational views/export, local restore, closed projection repair, restart-based HTTP operator rotation and read-only reference-aware retention planning. Full telemetry, coordinated deletion, whole-system restore and provider/replica rotation remain open. | Establish writer/hold/backup coordination before deletion; rehearse cross-system recovery and remaining credential/kill-switch paths. |
| M4-04 | missing; external prerequisite | No complete P-01–P-12 evidence matrix, validation promotion decision or human pilot signoff. | Close preceding gates; retain scenario manifests and actual authenticated operator signoff for a restricted pilot. |
| M5-01 | partial preparation; agent qualification required | E17: 36 real metadata candidates with pinned source/base/license provenance and proposed 12/12/12 groups; all UNQUALIFIED, zero scored. This is not the required qualified corpus or frozen campaign. | Qualify at least 30 tasks with actual independent agent curation, rights/oracle/linkage decisions, protected references and frozen splits. |
| M5-02 | partial | E8/E23: conservative reverse-import traversal, standalone bound coverage-context import/ranking, explicit unknowns and mandatory full suite. Product integration, AST edge provenance and paired full-suite comparison remain open. | Integrate qualified measured coverage and revision-bound AST provenance; compare full-suite outcomes without skipping mandatory checks. |
| M5-03 | partial tooling; campaign missing | E8: isolated scorer, strict missing-task denominator, Wilson interval and report CLI. Paired seeded bootstrap, missing-cost accounting and compare CLI now exist (E20). Preregistration/arm parity/scheduling/cap validation exist (E22); no executor, genuine arm execution or completed campaign. | Implement protocol-complete runner/result provenance and report comparisons, then execute the frozen campaign with actual agent scoring/usage records; leave unobserved human effort and benefit unmeasured. |
| M5-04 | missing | Documentation and a synthetic demonstration exist; no historical portfolio report, qualified outcomes or replayable evaluation package. | Publish measured task-level report, uncertainty/failures/costs/agent decisions and any actual human interventions and redacted reproducibility artifacts after M5-03. Report missed thresholds honestly. |

## Product acceptance gates P-01–P-12

| Gate | Status | Concrete scope proved / gap | Required next evidence |
| --- | --- | --- | --- |
| P-01 clear ticket | external prerequisite | E11 proves synthetic local candidate; no product-created GitHub App PR or real Linear review state. | One real authorized Linear ticket, exact candidate PR/evidence, independent checks/review and actual status handoff. |
| P-02 ambiguity | partial | Intake fixtures and revisioned clarification routes exist; Temporal test planner returns a fixed ready plan. | End-to-end ambiguous analysis, no execution while blocked, authenticated answer and fresh revision/plan; live source mapping. |
| P-03 risk | partial | High-risk fixtures and sensitive-change detectors reject named cases. Model must not lower observed risk. | Actual end-to-end high-risk/sensitive-diff rejection with zero unauthorized tools, publication or spend. |
| P-04 duplicates | partial | E29 adds real PG intake rollback/response-loss dedup and actual Temporal start/ack redelivery with one run; outbox lease fencing and mocked PR reconciliation also exist. | Extend terminal/active activity races and real provider redelivery showing one logical PR/status operation. |
| P-05 crash | partial | Real Temporal restart at human wait/replay and closed projection repair (E16). Neither is in-flight candidate recovery. | Crash active build, validator and publisher; reconcile provider/usage/resources, safely resume or terminate without duplicate effect. |
| P-06 evidence | partial | E13/E14/E15: structured collector attack regressions, strict referenced manifest gate, exact producer/head CI and changed PR-context invalidation. Live product CI and complete malicious-runtime/manual-evidence matrix remain open. | Retain actual forged/changed-head/base/policy/criteria denial evidence through onboarded final handoff; qualify residual semantic trust. |
| P-07 corrections | partial | Bounded loop is implemented; single live success has no repair; no full pipeline rejection-loop test found. | Reviewer requests changes, new candidate gets new checks/review, exhausted budget fails, all usage retained. |
| P-08 stop/budget | partial | E14/E25: finite reservations/CI deadlines, separate tracker gate and actual active Docker parent/child cancellation in 15.359s with durable CANCELLED, APPLIED command and no remaining labelled container. Cleanup uncertainty fails; approval expiry stops execution. | Extend to paid-model uncertainty, worker/daemon loss and complete no-post-ack effect/budget matrix; one bounded drill is not a general timing guarantee. |
| P-09 injection/secrets | partial | Real malicious dependency hook cannot read broker canary, Docker socket or external endpoints; protected paths and risk heuristics exist. | Repository/ticket/log injection and malicious tests cannot expand capabilities, forge readiness or access withheld artifacts; actual runtime evidence. |
| P-10 external outcome | external prerequisite | Signed observation code and fabricated merged/closed/stale tests exist. | Actual authorized product PR close/merge observation retained separately from agent status; no invented deployment status. |
| P-11 baseline | proved — controlled local route | E58/E65: actual failed baselines stop model/candidate work; Temporal persists failure and actual receipts, exposed through authenticated operator detail/worklist/audit. | Owned fixtures and automated test-role approval; no human receipt/resolution metric or live Linear onboarding is claimed. |
| P-12 provider fault | partial | E30: actual PostgreSQL with controlled 429/503/lost-response/cancellation retains unknown reservations and refuses a duplicate request; committed settlement recovers cached output after lost acknowledgement. | Extend integrated Temporal/provider recovery and actual billing reconciliation; controlled responses are not real outages or invoice evidence. |

No complete product gate is closed merely because its unit predicate passes. Some can be proved locally with controlled fault providers, but the integrated P-01/P-04/P-10 provider claims need actual onboarded systems.

## Named research recommendations ledger

Recommendations below consolidate the five reviews without omitting their original topics. ADR-007 explicitly supersedes human benchmark qualification/scoring with agent-led evidence at the user's request; historical human-benefit hypotheses remain unmeasured, not hidden release blockers. Human plan approval, merge authority and pilot signoff remain unchanged. Facts about vendor APIs are design inputs; their implementation requires the separate evidence shown here.

| Review / recommendation | Status | Evidence / next action |
| --- | --- | --- |
| Product: bounded Linear→GitHub Python scope | partial | E1/E5 establish scope and local execution; complete E7 live gates. |
| Product: three contexts, ordinary-code policy | proved — structure | E5 has planner, builder, fresh reviewer; E2/E3/E6 own policy/budget/execution. Review effectiveness remains unproved. |
| Product: security/evaluation before broad execution | partial | Security precedes execution; named summary-forgery regressions are now covered (E13). Qualified corpus and full security qualification remain open. |
| Product: assertions separated from execution evidence | partial | Structured collector, strict referenced manifest and producer-scoped CI gates exist (E13/E14); live provenance and semantic adequacy remain unproved. |
| Product: review readiness separate from delivery | proved — implementation contract | ADR-006 and E4/E7 keep draft handoff, human merge and separate observed outcomes; live observation still open. |
| Product: narrow context; no universal graph claim | partial | AST unknowns and full suite implemented; measured coverage/context selection absent. |
| Product: honest demo, names and no productivity claims | proved | README labels synthetic/local results; product/folder names retained; no claimed benchmark benefit. Keep current as work changes. |
| Product: review as hypothesis, total human effort and cost | empirical proof missing; benchmark method superseded | Historical recommendation retained. ADR-007 uses agent-led paired evaluation; actual human effort/benefit remains unmeasured and cannot be claimed. Implement equal-cap arms and measured automated costs. |
| Product: defer profiles/trackers/graphs/multi-tenancy | deferred-by-plan | M6 retains breadth; this does not defer required M5 bounded impact/evaluation work. |
| Architecture: modular package and narrow provider boundaries | proved — structure | E3–E8 and service CLI implement selected Python/Postgres/Temporal architecture. |
| Architecture: one authoritative durable lifecycle | partial | Temporal lifecycle and monotonic PG projection; E16 actually repairs closed projections with history validation/CAS. Active-work and full lag/race qualification remain open. |
| Architecture: receipts distinct from applied commands | proved — bounded control tests | E3/E4 persist canonical command IDs, disposition and expected sequence; complete connected race matrix. |
| Architecture: logical operation IDs and reconciliation | partial | E3/E5/E7 implement dedup and markers; live unknown-result recovery open. |
| Architecture: revision-bound plan/evidence/approval | partial | Use-time expiry/current role and strict input/config/plan/candidate/PR/CI bindings are implemented (E13/E14); complete connected/live qualification remains open. |
| Architecture: cancellation with bounded cleanup | partial | E25 proves one actual active Docker parent/child workload stops below 30 seconds; cleanup-error and expiry drills fail closed. Host/daemon/worker loss and paid-provider effects remain open. |
| Architecture: replay-compatible upgrades | partial | E27 supplies saved prior-commit synthetic histories and offline replay/negative control. More branches and supervised deployment/activity compatibility remain open. |
| Architecture: database constraints/session boundaries/migrations | partial | Migrations through 0006, atomic CI generations/snapshots and E16 projection repair augment E3; full crash/restore matrix remains open. |
| Security: deny outside prompt; no agent merge | partial qualification | No merge API; fixed tools/config/policy. Actual target App permissions/protection and end-to-end denial proofs pending. |
| Security: offline runtime plus actual host probes | partial | E6/E9 named controls proved; stronger isolation explicitly not claimed; finish specified hostile candidate/cleanup cases. |
| Security: credential-free builder and broker publication | partial | Actual canary absence and App token scope contract. Real App token/revocation/no-bypass proof pending. |
| Security: raw signature, signed freshness, semantic dedup | partial | E3 handles Linear timestamp and GitHub signature without invented timestamp. Complete actual redelivery/out-of-order reconciliation. |
| Security: approval expiration and changed-input invalidation | partial qualification | E25 checks current worker settings per protected operation and during execution; actual Docker expiry stops work. Polling/provider races and distributed revocation qualification remain open. |
| Security: authentic evidence, capability independence | partial | E13 structured collector/strict manifest and E14 independent CI close named gaps; same-interpreter semantic trust and live App/evaluator qualification remain open. |
| Evaluation: qualify individual tasks, oracle and rights | partial preparation | E17/E18: all 36 candidates remain UNQUALIFIED. ADR-007 supersedes human-curator names with actual agent provenance, deterministic qualification and unresolved-disagreement refusal; no task admitted. |
| Evaluation: acceptance vs regression, no empty/skipped success | partial | Separate scorer and structured completion/identity/phase checks reject named empty/skipped/early-exit cases (E13). Semantic oracle/rubric qualification remains open. |
| Evaluation: leak-free worker inputs and separate scorer | partial | `worker_input` omits reference/oracle; scorer checks path collisions. Actual export scan, protected immutable oracle, tamper tests and independent review absent. |
| Evaluation: 30+ tasks, grouped frozen splits, held-out repo | partial preparation | E17 proposes three 12-candidate repository groups; zero qualified, no frozen campaign or held-out result. |
| Evaluation: matched-cap A/B/C and all costs/retries | missing campaign | Budgets/scorer/report primitives exist; implement arms/executor/order/repeats/infrastructure accounting and execute protocol. |
| Evaluation: strict denominators, uncertainty and human rubric | partial; rubric requirement superseded | Historical recommendation retained; ADR-007 uses a calibrated automated rubric. Missing-task/Wilson and paired-bootstrap tooling exists (E20); calibrated scoring, full metrics and qualified campaign remain open. Human benefit stays unmeasured. |
| Evaluation: AST + measured coverage + full suite | partial | AST and full suite present; standalone coverage contexts/extractor binding now exist (E23). Product integration, qualified measurements and C-arm experiment remain open. |
| Delivery: dependency gates and truthful boundaries | partial | Plan/backlog label open gates; older product/research wording conflicts with ADR-006 and current status. Synchronize present-tense claims. |
| Delivery: strict risk values and ambiguous/high-risk fixture | proved — foundation | E2 tests coercion rejection, sensitive labels and deny metadata. Does not prove code-risk completeness. |
| Delivery: locked reproducibility and least-privilege CI | proved at E9 revision | `uv.lock`, pinned actions, no persisted checkout credential, Python matrix, build and actual integration jobs inspected. Recheck final revision. |
| Delivery: no placeholders masquerading as providers | proved — inspected paths | Real adapters explicitly fail unavailable operations; contract fixtures are tests. Product live handoff still unproved. |
| Delivery: keep secrets/answers out of context/source | partial qualification | Credential separation/secret CI plus metadata-only curation projection with excluded answer fields (E17); full historical worker-export scan and independent leakage review remain open. |
| Delivery: owner authorization for publication/license | partial / external prerequisite | Implementation PR/remote exist after historical setup. No LICENSE found; owner license selection remains external, not a reason to stop local engineering. Product publication needs its own App authorization. |

## Highest-priority local work

1. Extend the newly implemented structured collector, strict manifest and CI gate into the remaining malicious-runtime, manual-evidence and complete handoff matrix. Named stdout-forgery/early-exit tests now pass; same-interpreter reports still cannot attest arbitrary candidate semantics.
2. Extend the proved active Docker cancellation/expiry and cleanup-error cases to worker/host/daemon loss, paid-operation uncertainty and remaining provider races. Preserve CI event/poll race limitations and human merge authority.
3. Build protocol-complete campaign execution and A/B/C arms, qualification/result provenance and budget accounting. Use the 36 UNQUALIFIED candidates as preparation; execute actual independent agent qualification decisions before freezing eligible splits or opening held-out material.
4. Extend active-work crash recovery, saved replay branches, supervised upgrades and telemetry. Read-only retention planning and orderly local operator rotation now have bounded evidence; coordinated deletion, cross-system recovery and replica/provider credential rotation remain open.
5. Integrate the standalone measured coverage contexts and complete AST revision/extractor provenance, retaining mandatory full regression execution; perform paired evaluation with calibrated agent scoring and actual usage records after qualification; report human benefit as unmeasured.
6. Synchronize documentation and run final checks at the final changed revision. Keep live GitHub App/Linear access, agent benchmark qualification and human pilot signoff explicitly open as distinct gates.

## External prerequisites that must remain explicit

- Authorized GitHub App registration, installation on the selected target, key delivery outside agent context, callback and target branch protection; actual publication/reconciliation/observation scenarios.
- Authorized Linear organization/team/worker/API/signing configuration and reachable HTTPS callback; actual ticket delivery, replay, clarification and review-state update.
- Benchmark qualification is agent-led under ADR-007, so human curator names/scoring are no longer external prerequisites. Actual isolated agent executions and deterministic qualification evidence are still required. Human-effort/benefit claims remain unavailable without separately observed real human participation; never invent identities or minutes.
- Authorized repository/data usage, selected licensing, and any additional campaign spending authorization required by the user. The protocol's USD 1,000 cap is explicitly not spending permission.
- An authenticated operator's actual pilot signoff after the gates pass. Neither a test fixture nor a model statement is that signoff.

## Documentation synchronization

[ADR-007](adr/ADR-007-automated-benchmark-qualification.md) supersedes earlier active or historical references requiring two human benchmark curators or human rubric scoring. Preserve their historical wording with this annotation; use independent agent qualification/scoring and retain all eligibility, safety, split and budget requirements.

The initial audit identified the following historical wording for synchronization. ADR-006 deliberately changes publication order and keeps handoff draft. Where the product journey or retained plan/backlog paragraphs describe automatically marking ready after publication, state the superseding behavior in the active contract. Where the evaluation methodology describes its schema/scorer as entirely planned, partial tooling now exists; retain all remaining protocol requirements while updating that inventory. Research 05 says no hosted CI/remote/settings existed during the original setup; retain its historical date but link current E9/E10 status. Any plan wording that current records cannot authorize remote work should distinguish disabled configuration from missing broker implementation. The originally identified divergent policy labels are now replaced by a shared `POLICY_VERSION` used by execution configuration, candidate production and strict admission. Preserve that binding and its regressions; do not reopen the old labels as current behavior.

Closing this audit means every required row has concrete qualifying evidence, or an explicit external prerequisite remains unresolved. It does not mean changing partial rows to deferred, shrinking the historical evaluation, or treating the controlled synthetic run as the end-to-end product.

E35: The complete preparation/provenance checkpoint passed 941 tests with seven explicit Windows
skips in 261.66 seconds against actual PostgreSQL, Temporal and Docker. Ruff check/format
(165 files), mypy (62 sources), locked dependencies, wheel build, installed-wheel evaluation
ledger creation and new contract imports passed. These validate prerequisites; no qualifier
controller, calibration result or historical admission is implied. The real failed probe in E34
remains unresolved.

E36: [Infrastructure accounting](evaluation-execution-store.md) extends the dedicated ledger without
schema migration. The 52-case focused suite passed, including a separately created real PostgreSQL
database, mixed model/infrastructure budget races and immutable concurrent settlement. Infrastructure
uses zero model tokens and measured duration at a pinned estimated rate; model, infrastructure and
shared account ceilings include unknown reservations. No campaign-wide allocation or invoice proof.

E37: [Deterministic qualification runtime](qualification-runtime.md) executed actual preflight and
twelve synthetic Docker checks, then recovered the complete cached result without any repeated
execution. Thirty controlled tests cover collector faults, authority/expiry, immutable resume,
lost settlement acknowledgement, retained unknowns, repeated cancellation/cleanup joining,
read-only complete-chain validation and cross-repository store/ledger exclusion. All results retain
`admitted=false`; this is not historical oracle qualification or hostile-code attestation.

E38: [Protected review v2](qualification-v2.md) passed 32 focused tests for actual source/oracle
contexts, complete evidence citations, peer separation, sealed-output adjudication and exact settled
model-receipt bindings. Reference solutions/raw execution output remain excluded from model contexts.
Supporting imported prose remains trusted-producer material. No real model judgments or task
admission are claimed by controlled fixtures; v1 admission is not automatically upgraded.

E39: [Executed calibration](evaluation-calibration.md) passed 35 focused tests using the real
model broker, controlled HTTP transports and dedicated SQLite accounting. Exact frozen development
cases, rubric/prompt/schema/model/rates, response identity and ledger checkpoints bind recomputed
agreement/false-admit/mandatory-failure and usage metrics. Unknown calls cannot retry; lifetime
deadlines and post-response policy revocation apply. Independent review reproduced and verified
response-ID reuse rejection. No paid calibration, historical case or campaign ran. The integrated
qualifier and protocol migration were still pending at this checkpoint; E41 records their subsequent
bounded implementation without claiming live historical admission.

E40: Complete executable-stage verification passed 1056 tests with seven explicit Windows skips
in 356.95 seconds against actual PostgreSQL, Temporal and Docker. Ruff check/format (175 files),
mypy (65 sources), locked dependencies, wheel build, installed-wheel imports/infrastructure accounting,
53-document local link validation and staged secret scanning passed. No paid calibration, historical
admission or campaign ran. The previous checkpoint `379bfa6` passed all four hosted checks at
[run 36448350261](https://github.com/ahines99/agentic-delivery-os/actions/runs/36448350261).

E41: [ADR-011](adr/ADR-011-current-qualification-authority.md), the [complete controller](qualification-controller.md)
and [current authority](qualification-admission.md) connect preparation, executed calibration,
thirteen runtime effects, independent reviews, conditional adjudication and exact closed accounting.
Current export/scoring/campaign preparation require reconstructed v2 evidence and current action
permission; legacy records allow explicit inspection only. Twenty-four admission regressions use
genuine controlled-transport execution chains and cover chronology, current authority, exact caps,
unknown retention, synthetic refusal and export boundaries. An actual Docker integration exercises
qualification, admission, source-only export, a candidate score and cached resume. Model responses
and task provenance are synthetic fixtures; no historical catalog task is admitted. The earlier
E18/E39 statements that this controller was missing describe their prior checkpoints.

E42: [Separate scoring execution](scoring-execution.md) binds a distinct grant/account to the
qualification, task, candidate, configuration, policy, rate and lifetime deadline. Its 21 focused
tests cover per-stage metering, caps, current revocation, cancellation/cleanup, settled resume and
unknown retry refusal. Consumer migration passed 197 focused regressions; primitive tests use
explicit controlled authority fixtures, while E41 supplies complete-chain actual Docker evidence.
These counts are scoped runs, not additive coverage or calibrated scoring efficacy. Campaign-wide
allocation, live calibration, historical qualification and campaign execution remain open.

E43: Complete v2 controller/admission/consumer verification passed **1155 tests, seven explicit
Windows skips**, in 610.65 seconds against actual PostgreSQL, Temporal and Docker. Ruff check/format
(186 files), mypy (68 sources), locked dependencies, wheel build, installed-wheel imports,
57-document local link validation and staged secret scanning passed. No managed test container
remained after the full run. No paid provider call, historical qualification or campaign ran.
The previous `e2f94e9` checkpoint passed all four hosted checks at
[run 36451443398](https://github.com/ahines99/agentic-delivery-os/actions/runs/36451443398).


E44: [Owned calibration preparation](synthetic-preparation-runtime.md) connects five original
development examples, scoped internal-processing rights, actual-ledger review inputs and inert
review subjects. Known reference/expected-answer aggregates cannot be used as review documents
or rubrics. Sixteen new exclusions plus the subject/v2 suite passed 82 focused tests. Pure
[request forecasts](model-request-forecast.md) share actual broker serialization and reservation
rules. Full local verification passed **1318 tests, seven explicit Windows skips**, in 661.83
seconds with PostgreSQL, Temporal and Docker. Ruff check/format (207 files), mypy (73 sources),
locked dependencies, wheel build, installed-wheel imports, 247 local links across 64 documents
and staged secret scanning passed. No managed test container remained. At this source checkpoint
the real five-case preparation and paid calibration had not run; no historical task was qualified.


E45: [Actual owned preparation](synthetic-preparation-runtime.md#recorded-execution) completed
65 Docker operations with 130 microdollars of local infrastructure estimates and zero model
usage. Cached resume added no effects. [Live calibration](evaluation-calibration.md#recorded-live-development-calibration)
then settled five provider calls at $0.735425: five matching verdicts, one fully valid response,
zero false admits and two mandatory failures. Status is **CALIBRATION_FAILED**; the strict
evidence gate blocked qualification. All five operations settled and cached resume added no
spending. Frozen expected findings were unchanged. The preceding offline prompt-whitespace
repair retained original artifacts, unused identity and deadline. These results do not admit
any of the 36 historical candidates or satisfy benchmark/pilot gates.


E46: Final verification including the shared rubric/prompt normalization fix passed **1324
tests, seven explicit Windows skips**, in 601.71 seconds against actual PostgreSQL, Temporal
and Docker. The separate 136-test calibration/subject/v2/controller regression also passed
(one actual Docker test deselected there and included in the full suite). Ruff, formatting,
mypy, rebuilt installed-wheel prompt checks and locked dependencies passed. This software
verification does not override E45's failed live calibration or close historical/pilot gates.


E47: Explicit [target/citation guidance](qualifier-prompt-contract.md) preserves validators and
frozen expected decisions. A fresh five-call live calibration passed all five development cases
with zero false admits/mandatory failures, at $0.760480. Cached resume added no effects or cost.
The failed E45 stage remains retained; combined calibration cost is $1.495905 for ten calls.
This reused development set does not measure held-out accuracy or qualify a historical task.
Full local verification passed **1328 tests, seven Windows skips**, in 634.54 seconds with real
PostgreSQL, Temporal and Docker. Ruff/format (209 files), mypy (73 sources), locked dependencies,
wheel build and fresh installed-wheel imports passed.

E48: Subsequent synthetic qualification completed 13 actual Docker operations at
26 microdollars of local infrastructure estimates. The first model review returned
HTTP 200 with `max_tokens`, reporting 8,683 input and 5,000 output tokens. Its
234,400-microdollar reservation remains unresolved at this checkpoint; no complete
review was accepted. No second review, adjudication or qualification result followed,
and the operation was not retried or aliased. Cost-only failure reconciliation remains
separate from successful model evidence. Historical qualification remains at zero.

E49: [Evaluation-only failure reconciliation](model-failure-reconciliation.md) now
requires the exact original request, configuration, observation and reservation.
Forty-five focused tests passed, including actual PostgreSQL concurrent callers;
independent review and a separate 44-test run also passed. Applied to E48, it settled
168,415 microdollars of configured-rate model cost, with zero remaining reservation.
The failed receipt has no output or retry authority; cached reconciliation changed
nothing and made no provider call. Including 26 infrastructure microdollars, the
failed attempt cost 168,441 microdollars. The unrelated old probe remains unresolved.

E50: The [offline historical importer](historical-import.md) checks exact full-source
inventory, unchanged bytes, revision/reference/issue-time bindings and existing current
preparation policy before freezing metadata. Forty-one new synthetic tests plus the
preparation suite passed 118 tests with one explicit Windows skip. This imports already
acquired protected bundles only; it neither fetches real historical cases nor creates
rights, execution permission or admission. All 36 catalog candidates remain unqualified.

E51: A [metadata-only compatibility screen](evaluation-curation.md#development-compatibility-screen)
queried complete Git trees at the 12 proposed development bases. Every tree contains
at least one tracked file above the current 256-KiB per-file snapshot limit, so all
12 are unsupported under the existing full-source profile. No source/issue/answer
bytes or held-out repository content were read. Original candidates remain retained;
supported replacements or a validated profile extension are required before freeze.

E52: Complete local verification including the historical importer and failure-accounting
path passed **1414 tests, seven explicit Windows skips**, in 663.44 seconds with actual
PostgreSQL, Temporal and Docker. Ruff/format (215 files), mypy (75 source files), locked
dependencies, wheel build and fresh installed-wheel imports passed. All 268 local
document links and staged secret scanning passed. These software checks do not turn
the failed review into a qualification or resolve the historical compatibility gates.

E53: A separate five-call calibration with an 8,000-token output allowance and
180-second timeout retained the exact earlier development cases, expected findings,
rubric and prompt. It passed all five complete evidence contracts at $0.727535,
under an exact $1.610935 reservation ceiling; cached resume added no calls or cost.
All three calibration stages remain retained ($2.223440 combined). This validates
the revised configuration on those development cases only. A new finite synthetic
qualification was initialized separately after the prior failed attempt was closed.

E54: That fresh owned fixture completed **SYNTHETIC_VALIDATION_PASS** with 13 actual
Docker operations and two independent model reviews; agreement made adjudication
unnecessary. Complete authority reconstruction passed for synthetic validation while
all historical/export/scoring/campaign consumers remained denied. Model usage cost
$0.363880; infrastructure estimates added 26 microdollars. All operations settled,
cached recovery added no effects or charges, and no managed container remained.
Historical qualification is still zero. This closes the development demonstration
of the complete qualification path, not the historical evaluation or pilot gates.

E55: [Protected public baseline acquisition](historical-acquisition.md) now validates
fixed-origin public metadata, complete Git trees and every blob before writing protected
artifacts. The final acquisition/import regression passed 103 tests; independent security
review passed the preceding 61 acquisition cases. The separate whole offline worktree
suite passed 1420 tests with 62 service/Windows skips before the final cleanup-error guard
and its additional test; the final 62 acquisition tests cover that last change. Ruff/format
(218 files), mypy (76 sources) and commit secret scanning passed. A real credential-free
cachetools run acquired 43 files/230,124 source bytes in 46 reads, with zero repository
execution or model use. Cached validation added no network requests. It remains baseline-only,
unimported, unauthorized for execution and unqualified; no historical gate was closed.

E56: The integrated acquisition revision passed all **56 actual PostgreSQL, Temporal
and Docker integration tests** in 213.08 seconds. Its source/tests/scripts/runtime files
match the isolated implementation byte-for-byte; final focused coverage remains 103
passing acquisition/import tests, including the cleanup-error guard. Locked dependencies,
rebuilt wheel and fresh installed-wheel acquisition/import/reconciliation imports passed.
These split validation results are recorded separately from the earlier 1414-test full
service-enabled suite and from the pre-final-guard offline suite; counts are not added
into an invented single full-run total.

E57: Exact-head [hosted CI at 3dda278](https://github.com/ahines99/agentic-delivery-os/actions/runs/36472528826)
passed all four checks: **1428 passed, 55 skipped** on both Python 3.12 and 3.13,
plus **56 actual-service integration tests**. Ruff/format checked 218 files and mypy
checked 76 sources. This is the acquisition checkpoint before the next additions.

E58: Two [deliberately failing baseline checks](baseline-failure.md) passed against
the actual Docker pipeline in 6.64 seconds. Assertion and collection failures retain
their real receipts, with no model generation/reservation, candidate or readiness.
Both preflights and baselines ran, and all four exact containers were absent afterward.
This closes the local failure-evidence gap, not Temporal/human-triage routing.

E59: [Protected issue acquisition](historical-requirements.md) passed 57 synthetic
tests and independent review; the combined requirements/baseline/import scope passed
160 tests. A real three-query capture preserved the replacement issue's 2,956-byte
body and matching provider-reported no-edit chronology before the supplied acceptance
time. Cached validation added no requests. No historical text entered implementation
context and no model/code execution occurred. The separate current title remains
historically unverified; archival proof, rights clearance and admission remain false.

E60: Protected [license observations](historical-input-provenance.md) bind matching
MIT license text and an earlier provider-reported license change to the same baseline.
Separate accepted-PR metadata identifies two modified paths, one an original test.
The current reference contract preserves original tests, so an explicit derivation
design is needed; silently omitting that change would not reproduce the accepted tree.
Static metadata also identifies a source layout without configured pytest import paths.
No accepted patch or test answer was inspected interactively. Historical imports and
qualified tasks remain zero.

E61: The complete local suite at source revision `abd4bb8` passed **1535 tests,
seven explicit Windows skips**, in 656.85 seconds with actual PostgreSQL, Temporal
and Docker. Ruff/format checked 224 files and mypy checked 77 sources. Locked
dependencies, wheel build and fresh installed-wheel imports passed. This full run
includes issue acquisition and the deliberately failing delivery baselines; it
precedes the subsequent optional donor-reuse change.

E62: Optional protected donor reuse revalidates the complete donor inventory/source
and matches recomputed Git blob hashes and sizes against the fresh complete target
tree. It preserves existing result serialization and transfers no rights or authority.
The final integrated acquisition/import/requirements suite passed **187 tests** in
11.41 seconds; independent review passed all 27 new donor cases. The source-layout
and versioned reference derivation in [ADR-013](adr/ADR-013-derived-historical-reference.md)
remain accepted design, not implemented functionality.

E63: [Accepted-tree acquisition](historical-acquisition.md#recorded-accepted-tree-acquisition-with-reuse)
captured all 43 files/231,483 bytes at the candidate's accepted commit, using five
snapshot requests and one parent-link check. Cached validation added no requests.
A protected AST feasibility check found three added direct test candidates in the
changed original test file, alongside one implementation-change candidate. No test
identities or source/answer contents entered implementation context. No oracle,
executable derived reference, rights grant, model/code execution or qualified task
was produced. The full accepted tree remains protected reference evidence.

E64: After donor integration, Ruff/format checked 225 files, mypy checked 77 sources,
and the final wheel rebuilt and passed installed-package imports including the donor
API. All 291 local links across 73 inspected documents resolved, and no managed
container remained. The 1535-test service-enabled run and later 187-test acquisition
run remain separate recorded scopes; no larger full local run is inferred from them.

E65: [Durable baseline triage](baseline-failure.md#durable-operator-routing-follow-up)
passed one actual PostgreSQL/Temporal/Docker/loopback-HTTP test in 6.35 seconds.
A frozen planner fixture and authenticated test-role approval reach the real candidate
activity. Its failing baseline produces durable `FAILED`, preserved collector evidence,
operator worklist/detail/audit visibility and successful history replay. Unauthenticated
detail is denied; no model call/reservation, candidate, readiness or publication occurs,
and no container for the run remains. This proves the technical local routing required
by P-11, not actual human observation, live tracker onboarding or broader pilot completion.

E66: At source `c35685d`, the integrated baseline-triage, source-layout, evidence-manifest,
historical derivation, import, acquisition and requirements scope passed **342 tests,
three explicit Windows symlink skips**, in 50.64 seconds. Actual PostgreSQL, Temporal,
Docker and authenticated loopback HTTP exercised the durable failure route again.
The new immutable collector image also exercised bounded source imports and flat-layout
compatibility. Ruff/format checked 231 files and mypy checked 78 sources. This is a
targeted suite, not a new full-suite count. CI now selects the built image for source-layout
integration cases as well as ordinary sandbox cases.

E67: The [protected development observations](historical-reference-derivation.md#subsequent-protected-development-observations)
retain a cachetools derivation refusal and a subsequent schedule derivation success.
A twelve-lead metadata-only screen retained ten unsupported and two potentially eligible
outcomes. The first eligible schedule lead produced exact protected derivation with two
frozen acceptance selectors, but no rights grant, task import, runtime qualification or
model call. Separate issue and license observations remain evidence ingredients, not
historical admission. All 36 original catalog candidates remain unqualified.

E68: The full local suite at source `f669d72` passed **1675 tests, ten explicit
Windows skips**, in 707.25 seconds with actual PostgreSQL, Temporal and Docker.
This includes the new collector, pipeline evidence and standalone derivation, but
precedes versioned import/linkage/authorization integration. It is distinct from
the earlier 342-test focused run. The four new commits through that source passed
secret scanning, and the locked dependency check resolved 45 packages unchanged.

E69: After versioned import, explicit derived-data authorization, input resolution and
active expiry integration, the evaluation regression scope at `6129dea` passed
**863 tests, two explicit Windows skips**, in 479.33 seconds. It covered historical,
qualification, synthetic, calibration and scoring modules with actual service variables
configured. Independent owned mutations also denied either authorization pin revoked,
fully rebound task wording, unverified title/reference aliases, wrapper stripping and
expiry during active runtime/model work. This later focused scope is not summed with
the earlier 1675-test full run. Ruff/format checked 241 files and mypy checked 81 sources;
the wheel built and imported from a fresh offline-installed environment. All 294 local
links across 76 inspected documents resolved; the 13 new commits passed secret scanning.

E70: Two bounded fixed-query provider metadata captures for schedule PR 463/issue 175
agreed and passed the new linkage validator, including requirements strictly preceding
the accepted commit timestamp, the exact acquired tree/sole baseline parent, and the
merged PR's issue-closing event. Cached revalidation against integrated source added
no network calls. These provider assertions do not establish cryptographic authenticity,
rights, historical runtime success or admission. Actual historical imports and qualified
tasks remain zero; no new model spend or historical code execution occurred.
