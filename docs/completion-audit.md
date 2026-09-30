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
| M1-08 | partial; corpus qualification required | E17/E75/E76: the original 36 metadata candidates remain UNQUALIFIED; two separately acquired development tasks passed deterministic checks, two independent reviews and current admission authority. No historical scoring or campaign. | Extend qualification with rights/linkage, oracle stability, independent provenance and final frozen splits. |
| M2-01 | partial | E6/E9 prove actual named Docker resource, egress, filesystem and credential probes. Broader malicious runtime/cleanup/host-admission qualification remains open. | Extend adversarial cases on the selected host; document residual shared-kernel risk and fail release on unresolved bypasses. |
| M2-02 | partial | E6/E11: exact Git snapshot, fixed image, separated offline execution and real passing baseline. No general dependency bundle/lock qualification path for multiple historical repositories. | Add pinned dependency preparation/provenance and a failing-baseline integration case; retain installation/baseline records. |
| M2-03 | partial | E5/E6: typed edit proposal replaces arbitrary tools; policy and budget sit outside prompt. Real builder ran. Fault/authorization matrix and development provider qualification incomplete. | Exercise schema/rate-limit/cancel/errors and demonstrate no execution or spend following denied admission. |
| M2-04 | partial | E6/E11: safe paths, symlink rejection, original tests/protected configuration, exact old-content hashes, immutable candidate/diff artifacts. Complete hostile-output and candidate-reproduction matrix absent. | Verify candidate reproduction and add symlink/traversal/size/secret cases across the entire builder-to-publisher boundary. |
| M2-05 | partial | E6/E13: image-owned structured pytest collection replaces stdout verdicts; completion, identities/phases, minimum counts and execution bindings are checked. Named forged-summary/early-exit cases now have actual Docker tests. Candidate code still shares the collector interpreter. | Qualify malicious runtime/oracle cases and independent behavioral checks; do not treat structured reports as semantic attestation. |
| M3-01 | external prerequisite, with partial code | E7: scoped App token broker, branch/tree/PR markers, final exact-ref reread, no merge API; HTTP contract tests only. E10 is not a product App PR. | Install authorized least-permission App; exercise real draft creation, unknown response reconciliation, duplicate/head/base races, token revocation and no-bypass protection. |
| M3-02 | partial | E5/E11/E77: fresh reviewer context and a live approving result; actual Docker with controlled model responses proves rejection, repair with fresh validation/review, and normal exhaustion. | Retain a live development model rejection/repair result; maintain separate capabilities and shared budgets. |
| M3-03 | partial | E13/E14/E15: strict manifest/reference validation, structured collection and independent producer-scoped CI observations/reconciliation are implemented and fixture tested; fresh synthetic manifest passed the gate. Live App check evidence and complete manual pending/denial handling remain open. | Exercise the full onboarded product chain, manual evidence semantics and remaining adversarial provenance/race matrix. |
| M3-04 | external prerequisite, with partial code | E7: Linear state adapter and signed GitHub PR observations, staleness/merge/closed records. No actual Linear→product PR→observed close/merge run. ADR-006 keeps PR draft for human review. | Complete live integration sequence and preserve signed receipts and revision tuple; human performs readiness/merge. Do not infer deployment. |
| M3-05 | partial engine; campaign missing | E78/E79 provide a shared A/B candidate engine and explicit frozen execution-budget contract. No historical A/B campaign or validation promotion result. | Implement the authorized campaign executor and calibrated final scoring; qualify tasks and execute equal-cap arms while leaving the sealed split unopened. |
| M4-01 | partial | E3/E4/E7/E25/E27/E29/E30 cover fixture faults, wait restart, replay, active Docker cancellation, PG rollback/redelivery and model reservation recovery. E80 proves actual candidate-worker process loss with bounded cleanup or explicit UNKNOWN and no repeated candidate call. | Extend daemon/host loss, distributed fencing, paid-model cancellation and actual-provider lost-response reconciliation; retain one-effect evidence. |
| M4-02 | partial ? release qualification open | E2/E6/E7/E13/E14: named forged-summary/early-exit paths now rejected; strict manifest and CI producer/revision/rerun guards have regressions. Complete prompt-injection, malicious oracle and race qualification remains open. | Execute the full P-03/P-06/P-09/P-11 matrix on the actual selected runtime; investigate same-interpreter evidence limitations. |
| M4-03 | partial | E3/E12/E16/E19/E26/E28: operational views/export, local restore, closed projection repair, restart-based HTTP operator rotation and read-only reference-aware retention planning. Full telemetry, coordinated deletion, whole-system restore and provider/replica rotation remain open. | Establish writer/hold/backup coordination before deletion; rehearse cross-system recovery and remaining credential/kill-switch paths. |
| M4-04 | missing; external prerequisite | No complete P-01–P-12 evidence matrix, validation promotion decision or human pilot signoff. | Close preceding gates; retain scenario manifests and actual authenticated operator signoff for a restricted pilot. |
| M5-01 | partial; corpus qualification required | E17/E75/E76: original 36 metadata candidates remain UNQUALIFIED; two separate development tasks are qualified, zero scored. Proposed groups are not the required eligible corpus or frozen campaign. | Qualify at least 30 tasks with actual independent agent curation, rights/oracle/linkage decisions, protected references and frozen splits. |
| M5-02 | partial | E8/E23: conservative reverse-import traversal, standalone bound coverage-context import/ranking, explicit unknowns and mandatory full suite. Product integration, AST edge provenance and paired full-suite comparison remain open. | Integrate qualified measured coverage and revision-bound AST provenance; compare full-suite outcomes without skipping mandatory checks. |
| M5-03 | partial tooling; campaign missing | E8/E20/E22 provide deterministic scoring, strict denominators, intervals, paired comparisons and preregistration. E78/E79 add controlled A/B candidate execution and schema-3 frozen arm budgets; no historical executor or campaign. | Implement protocol-complete execution and calibrated final semantic scoring with shared attempt accounting; execute frozen comparisons and leave unobserved human benefit unmeasured. |
| M5-04 | missing | Documentation and a synthetic demonstration exist; no historical portfolio report, qualified outcomes or replayable evaluation package. | Publish measured task-level report, uncertainty/failures/costs/agent decisions and any actual human interventions and redacted reproducibility artifacts after M5-03. Report missed thresholds honestly. |

## Product acceptance gates P-01–P-12

| Gate | Status | Concrete scope proved / gap | Required next evidence |
| --- | --- | --- | --- |
| P-01 clear ticket | external prerequisite | E11 proves synthetic local candidate; no product-created GitHub App PR or real Linear review state. | One real authorized Linear ticket, exact candidate PR/evidence, independent checks/review and actual status handoff. |
| P-02 ambiguity | partial | Intake fixtures and revisioned clarification routes exist; Temporal test planner returns a fixed ready plan. | End-to-end ambiguous analysis, no execution while blocked, authenticated answer and fresh revision/plan; live source mapping. |
| P-03 risk | partial | High-risk fixtures and sensitive-change detectors reject named cases. Model must not lower observed risk. | Actual end-to-end high-risk/sensitive-diff rejection with zero unauthorized tools, publication or spend. |
| P-04 duplicates | partial | E29 adds real PG intake rollback/response-loss dedup and actual Temporal start/ack redelivery with one run; outbox lease fencing and mocked PR reconciliation also exist. | Extend terminal/active activity races and real provider redelivery showing one logical PR/status operation. |
| P-05 crash | partial | E16 proves closed projection repair. E80 kills the actual worker during candidate validation; replacement processing terminates without repeating candidate execution and records verified cleanup or UNKNOWN. | Extend active model/publisher and daemon/host-loss recovery; prove distributed fencing and reconcile provider usage/effects. |
| P-06 evidence | partial | E13/E14/E15: structured collector attack regressions, strict referenced manifest gate, exact producer/head CI and changed PR-context invalidation. Live product CI and complete malicious-runtime/manual-evidence matrix remain open. | Retain actual forged/changed-head/base/policy/criteria denial evidence through onboarded final handoff; qualify residual semantic trust. |
| P-07 corrections | proved — controlled local route | E77: actual Docker and controlled model responses exercise rejection, repaired candidate with fresh checks/review, exhaustion and retained usage. | Measure actual model correction quality in authorized development runs; this local proof does not establish historical effectiveness or human review. |
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
| Architecture: cancellation with bounded cleanup | partial | E25 proves actual active Docker cancellation, cleanup-error and expiry handling. E80 adds killed-worker cleanup or explicit UNKNOWN. Host/daemon loss, surviving-worker fencing and paid-provider effects remain open. |
| Architecture: replay-compatible upgrades | partial | E27 supplies saved prior-commit synthetic histories and offline replay/negative control. More branches and supervised deployment/activity compatibility remain open. |
| Architecture: database constraints/session boundaries/migrations | partial | Migrations through 0006, atomic CI generations/snapshots and E16 projection repair augment E3; full crash/restore matrix remains open. |
| Security: deny outside prompt; no agent merge | partial qualification | No merge API; fixed tools/config/policy. Actual target App permissions/protection and end-to-end denial proofs pending. |
| Security: offline runtime plus actual host probes | partial | E6/E9 named controls proved; stronger isolation explicitly not claimed; finish specified hostile candidate/cleanup cases. |
| Security: credential-free builder and broker publication | partial | Actual canary absence and App token scope contract. Real App token/revocation/no-bypass proof pending. |
| Security: raw signature, signed freshness, semantic dedup | partial | E3 handles Linear timestamp and GitHub signature without invented timestamp. Complete actual redelivery/out-of-order reconciliation. |
| Security: approval expiration and changed-input invalidation | partial qualification | E25 checks current worker settings per protected operation and during execution; actual Docker expiry stops work. Polling/provider races and distributed revocation qualification remain open. |
| Security: authentic evidence, capability independence | partial | E13 structured collector/strict manifest and E14 independent CI close named gaps; same-interpreter semantic trust and live App/evaluator qualification remain open. |
| Evaluation: qualify individual tasks, oracle and rights | partial corpus | E17/E75/E76: original 36 remain UNQUALIFIED; two separate development tasks have executed qualification and current admission authority under ADR-007. No scoring or campaign. |
| Evaluation: acceptance vs regression, no empty/skipped success | partial | Separate scorer and structured completion/identity/phase checks reject named empty/skipped/early-exit cases (E13). Semantic oracle/rubric qualification remains open. |
| Evaluation: leak-free worker inputs and separate scorer | partial | `worker_input` omits reference/oracle; scorer checks path collisions. Actual export scan, protected immutable oracle, tamper tests and independent review absent. |
| Evaluation: 30+ tasks, grouped frozen splits, held-out repo | partial corpus | E17 proposes three 12-candidate groups; E75/E76 add two separately qualified development tasks. No eligible 30-task corpus, frozen campaign or held-out result. |
| Evaluation: matched-cap A/B/C and all costs/retries | missing campaign | E78/E79 add a shared A/B engine and explicit frozen execution budgets. Campaign execution, calibrated final scoring, C-arm integration and complete attempt accounting remain open. |
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

E71: At implementation `31788de`, schedule PR 463 / issue 175 received exact finite
parent/derived data authorizations and completed actual protected v2 import. The
controller retained four public-attribution markers and a separate purpose-limited
decision, rather than declaring no personal data or exhaustive rights clearance.
Current core validation reused the existing five-case calibration and copied only
its 124 validated artifact dependencies; zero new calibration/model calls occurred.
This advances actual historical import, not historical admission.

E72: The first [historical runtime attempts](historical-development-attempts.md)
preserved a missing `mock` dependency failure, then performed a separately authorized
environment correction with a pinned wheel/image. All source, tests, commands and
selectors remained unchanged. The second baseline acceptance run collected both
frozen nodes and observed one passing and one failing, so the all-fail qualification
gate stopped it. Four infrastructure operations across both attempts settled for
8 microdollars at the configured local duration estimate, with no unknown reservation
or model call. Reference and regression suites were not reached; the task remains
unqualified. Image preparation is separately recorded and not included in that ledger
cost. The original 36 candidates, minimum corpus and release criteria remain unchanged.

E73: Schedule PR 404 / issue 304 completed a separate protected import with exact
finite data authorizations and all thirteen deterministic operations. Three frozen
acceptance nodes failed on the baseline and passed on the reference; 26 original
regressions passed on both variants, across three repetitions. The first protected
model review then hit its 8,000 output-token limit. Provider usage metadata supported
financial-only reconciliation: 68,115 input and 8,000 output tokens, 540,575 model
microdollars plus 26 estimated infrastructure microdollars, zero remaining reservation.
No valid review checkpoint, second review, adjudication, admission, export or scoring
resulted. The failed call remains recorded and its partial output was not inspected
by implementation agents. This is deterministic qualification evidence, not builder
performance or a completed historical benchmark.

E74: A separate five-call calibration increased only output capacity to 20,000 tokens
and timeout to 300 seconds. Original fixture artifacts, expected findings, prompt,
rubric and schema remained unchanged. All five valid outputs matched their frozen
expectations, with zero false admits or mandatory failures. Usage was 48,575 input
and 20,867 output tokens, costing 764,550 microdollars; all five operations settled
with zero reservation. The four retained calibration stages total 2,987,990 model
microdollars across twenty calls. This is reused development calibration, not held-out
accuracy or historical admission.

E75: A fresh PR 404 attempt used the newly calibrated output/timeout limits with all
historical source, tests, commands and selectors unchanged. All thirteen deterministic
operations passed again, followed by two agreeing independent model reviews. The
record passed current historical qualification authority validation: one admitted
development task. Model usage was 136,240 input and 19,371 output tokens, costing
1,165,475 microdollars; 26 estimated infrastructure microdollars brought this attempt
to 1,165,501. All fifteen operations settled with zero reservation. The earlier failed
attempt remains retained, so combined PR 404 qualification cost is 1,706,102
microdollars, excluding separate calibration/environment preparation. No worker export,
scoring or campaign authority resulted. The original 36 metadata candidates and full
30+ task corpus gate remain unchanged.

E76: Schedule PR 337 / issue 331 completed a third protected development import.
A retained unauthenticated acquisition refusal was followed by bounded operator-only
authenticated public reads. A separate import setup refusal preceded an explicit
correction of missing empty output/worker scopes; no historical source/test selector
changed. All thirteen deterministic operations passed: one acceptance node failed on
the baseline and passed on the reference, and all 24 original regressions passed on
both variants, across three repetitions. Two independent reviews agreed and current
authority admitted the task. Model usage was 120,755 input and 16,046 output tokens,
costing 1,004,925 microdollars; 26 estimated infrastructure microdollars brought the
attempt to 1,004,951. All fifteen operations settled with zero reservation. Two
development tasks are now qualified, with no historical scoring or campaign execution.

E77: The [controlled correction loop](correction-loop.md) now has two actual-Docker
cases for rejection followed by repair/approval and normal repair exhaustion. Each
case verifies fresh candidate receipts, unchanged original tests, retained attempts,
four settled scripted model operations and absence of all created containers. The
approved manifest passes production validation; exhaustion produces no readiness.
These are controlled local P-07/M3-02 proofs, not actual model quality or human review.

E78: A [shared candidate engine](candidate-arms.md) now implements a genuine
builder-only path with zero independent-review calls and a separate self-checked
result. The product wrapper always selects independent review and retains its public
result contract. Internal failure results preserve final candidate bytes for later
one-way scoring. Follow-up tests close inherited gaps in nested/suffix original-test
protection and duplicate reviewer verdicts. The isolated integration scope passed
94 tests before that follow-up; the follow-up passed 101 focused cases and four
actual-Docker cases. These overlapping scopes are not summed. The engine does not
implement campaign authority, shared spending allocation or final semantic scoring.

E79: [ADR-014](adr/ADR-014-campaign-execution-budgets.md) adds explicit schema-3
campaign freezing with execution caps taken from equal arm configurations while
preserving admitted task bytes. Legacy schema-2 exact budget equality is unchanged.
All current authority, calibration, corpus, split, parity and overall cap checks
remain required. The 58-case campaign contract scope passed; its authority boundary
is an owned test injection, not an actual corpus. No execution account or spending
permission is created, and versioned execution/scoring consumers remain open.

E80: An [actual worker-process-loss drill](worker-process-loss.md) initially exposed
an orphaned candidate container after heartbeat failure. The workflow did not repeat
the builder, but the test parent had to remove the container. The bounded cleanup
fix in [ADR-015](adr/ADR-015-bounded-candidate-cleanup.md) now uses a separate trusted
activity to inspect and remove only exact workflow-owned container IDs before
terminal projection. Two actual hard-kill drills passed: normal automatic cleanup
required no parent fallback; an injected cleanup failure persisted `UNKNOWN` and
required explicit parent cleanup. Both preserved one candidate invocation and one
settled scripted builder operation without reviewer/publication calls. Three actual
cancellation/expiry cases and 39 focused cleanup/authorization/replay cases passed
separately. The retained pre-fix failure history replays against the new workflow
patch without effects. This proves current-host cleanup after the tested worker
death, not fencing a surviving partitioned worker or universal recovery.

E81: Combined source `9058c73` passed the full service-enabled suite: **1854 passed,
ten explicit Windows skips**, in 787.69 seconds, with actual PostgreSQL, Temporal
and Docker. The disposable database was dropped and its absence verified. Ruff
check/format (254 files), mypy (82 sources), locked dependency validation, package
build, fresh wheel installation and new-commit/staged secret scanning passed.
All checked local links across 82 Markdown documents resolved. This integrated
scope includes E77–E80 and is not added to earlier counts. Subsequent isolated
scoring implementation and exact-head hosted CI are separate evidence.

E82: [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36494661795)
passed all four checks at `373cf34`: 1788 tests with 76 skips on each Python version
and 77 actual PostgreSQL/Temporal/Docker tests. This documentation checkpoint retains
production source `9058c73`; it precedes the scoring changes below. Counts overlap
the full local scope and must not be summed.

E83: The [versioned campaign scoring consumer](campaign-scoring.md) reads exact
schema-3 arm limits, a current per-attempt grant and an existing immutable account.
It preserves original qualified task bytes, deadline and prior usage, and allocates
no capacity. Legacy scoring is unchanged. The initial 35 new and 121 affected legacy
tests passed with explicit qualification/Docker substitutions; they do not constitute
historical execution. Independent review then exposed impossible ledger chronology
and missing collector nonce acceptance, addressed by thirteen additional regressions.

E84: [Protected semantic contexts](semantic-scoring-context.md) passed 41 owned tests:
exact source/candidate/oracle projections, observed receipt facts, current authority,
reference/log exclusion and complete structurally valid cited findings. Independent
review repeated that scope successfully. The actual model executor, semantic
calibration, sealed independent scorer receipts and adjudication remain separate.

E85: Five [original scoring subjects](semantic-scoring-examples.md) separate authored
expectations and diagnostic counterexamples from model-visible material. Twenty-four
authoring tests pass. Independent review clarified ordering versus full occurrence
retention so expected criterion labels do not conflict. [Owned runtime preparation](owned-semantic-runtime.md)
then passed 25 controlled authority/accounting/tamper cases and five actual Docker
cases (23.70 seconds), with no model calls or historical admission. A review found
and fixed a completed-evidence grant-rotation race; original reservation columns and
checkpoint chronology also have regressions. These are owned execution proofs,
not a calibrated scorer, historical score or campaign result.

E86: Combined source `3956b29` passed **1997 tests with ten explicit Windows skips**
in 957.33 seconds using actual PostgreSQL, Temporal and Docker. The disposable
database was dropped and absence verified. Ruff/format (267 files), mypy (86 sources),
locked dependency validation, package build and new-commit secret scanning passed.
This integrated scope includes E83–E85 and overlaps earlier counts.

E87: A separate retained execution of all five original semantic subjects completed
fifteen actual Docker operations with 30 estimated infrastructure microdollars,
zero model calls and zero remaining reservation. Exact cached recovery changed
neither operations nor charges. Its status is `EXECUTED_NOT_CALIBRATED`; it admits
no historical task and supplies no final-scoring calibration or campaign result.

E88: [Hosted CI at `81e588c`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36497999987)
passed all four checks: 1926 tests with 81 skips on each Python version (200.08 and
165.23 seconds), plus 82 actual PostgreSQL/Temporal/Docker tests in 231.60 seconds.
The checkpoint retains source `3956b29`. These scopes overlap E86 and are not summed.

E89: [Canonical allocation](campaign-allocation.md) now creates one finite account
per frozen campaign ordinal on an exact trusted ledger target. Owned SQLite and
six-controller actual PostgreSQL tests cover concurrency, partial-write recovery,
original deadlines and unchanged capacity. Independent review found and fixed
zero-cost prior operations being overlooked during partial allocation recovery.
The exact disposable PostgreSQL database was removed after its passing test.

E90: [Owned context authority](owned-semantic-context.md) reconstructs current
runtime evidence and exact projections without impersonating a historical task.
Independent review found no remaining blocker. Root integration of the context,
allocator and existing scorer passed 148 focused tests in 101.17 seconds; the
dedicated PostgreSQL case skipped there and passed separately as E89 records.
This scope included the actual owned-context Docker case and overlaps earlier tests.

E91: [Final-scorer calibration machinery](semantic-calibration.md) passed 33 tests
in 210.17 seconds, including five actual Docker preparations with controlled model
responses; four additional current-policy revocation tests passed separately.
Review found and fixed a missing-operation resume bug that could repeat a completed
call, plus active reservation token reconciliation. The reviewer independently
passed three focused regressions. These are machinery tests, not live model accuracy.

E92: The first [live final-scorer calibration](semantic-calibration.md#first-live-development-attempt)
stopped on the third call with HTTP 400. Two calls settled for 240,050 microdollars;
the third retains a 558,270 microdollar reservation without usage evidence. A separate
single-call capability diagnostic returned the same HTTP status and a billing-limit
hint, retaining its 20,495 microdollar reservation. Neither account was reset or
retried. No final-scorer calibration passed and no historical scoring was authorized.

E93: The service-enabled run at `5480789` completed with 2093 passed, eleven skips
and one failure in 1186.90 seconds. Ten skips are Windows-specific; one needs the
separate allocation database. That allocation case passed separately on actual
PostgreSQL in 2.76 seconds, with its database removed and absence verified. The
failure exposed an actual-clock test fixture retaining a hardcoded data-use expiry:
advancing its clock 31 minutes crossed midnight and correctly triggered rejection.
Commit `613c1d1` gives this fixture dates relative to construction, without changing
production expiry rules. All 37 affected qualification tests then passed in 192.86
seconds; one actual integration case was deselected in that focused run. A new full
combined result is required; the earlier run is retained as failed evidence.

E94: [Canonical A/B candidate execution](campaign-candidate.md) passed 41 focused
tests, including actual Docker builder-only and independent-review rejection/repair
paths. A separate 120-case affected engine/allocation/scoring scope passed. Independent
review caught and fixed replay after missing settled rows; the reviewer passed four
recovery regressions. Frozen model/rate fields now bind cached receipts explicitly.
All model responses in these tests are controlled, with no paid or historical work.

E95: [Two initial final scorers](semantic-execution.md) passed 119 combined tests
(31 new plus existing scorer/context cases) in 159.32 seconds. Independent review
passed twelve lease, cancellation, accounting and tamper cases. A private parent-task
lease permits only the exact planned active reservation while public readers remain
idle-only. Current calibration and authority, original capacity/deadline and immutable
receipts are required. Two agreeing reviews may establish the scoped semantic result;
disagreement remains unresolved. No adjudication or historical score was executed.

E96: Root integration of the candidate and two-initial-scorer executors passed 72
focused tests in 116.05 seconds, including actual Docker A/B repair paths with
controlled model responses. This overlaps E94/E95 and is not a full-suite result.

E97: [Read-only candidate inspection](candidate-inspection.md) reconstructs exact
A/B contexts, operation receipts, infrastructure accounting, collector nonces and
final bytes under separate current consumption authority. It performs no credential
lookup, provider call, execution, write or repair. Forty-three owned tests passed in
42.37 seconds; independent review passed the preceding forty-test scope and verified
the corrected infrastructure reservation binding. Expired execution may be inspected
only with current qualification/data-use permission; it cannot resume spending.

E98: After user-confirmed billing restoration, a fresh one-call diagnostic succeeded
for 1,670 microdollars. A separately authorized five-case final-scorer calibration
then completed at `48bb0de`, settling 597,710 microdollars with zero reservation and
unchanged cached recovery. It failed calibration: five overall verdict matches,
three valid exact matches, two mandatory structural failures and zero false-ready.
A fixed-code diagnostic identified one file-line-range and two acceptance-node
citation violations, without exposing outputs. Original failed attempts/reservations
remain retained. This is development evidence, not historical accuracy or admission.

E99: Separate [adjudication contracts](semantic-adjudication-contracts.md) distinguish
authored original peer findings from unverified historical receipt claims. Structural
merge resolves exactly disputed targets, preserves agreed statuses and lets cited new
concerns block a would-be PASS without establishing authority or strict success.
Five authored dispute anchors retain expectations separately. Independent review and
root integration each passed all 55 focused tests (1.16 and 0.91 seconds). No model,
container, historical adjudication or adjudicator calibration ran in this slice.
Root static checks passed with 290 formatted files and 94 typed source files.

E100: [Hosted CI at `9438b47`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36502328714)
passed all four checks: 2165 tests with 86 explicit skips on Python 3.12 and 3.13
(357.57 and 266.39 seconds), plus 87 actual PostgreSQL/Temporal/Docker tests in
233.43 seconds. This checkpoint retains production source `8555fcf`, including
canonical candidate execution, both initial scorers, read-only candidate inspection
and authored adjudication contracts. The dedicated allocation database was provisioned
and removed by CI. Secret scanning, lint, formatting, typing and package builds passed.
These scopes overlap; they are not summed. E102 records the completed local full
suite and its separate setup correction; no live calibration success or historical
campaign is implied.

E101: Explicit v2 citation instructions preserve original v1 prompt bytes and require
exact artifact resolution in both calibration and initial semantic execution. At
reviewed source `5ca56d3`, 96 controlled tests passed with one optional Docker skip;
root independently passed 23 version/rebinding controls in 11.75 seconds. A fresh
4,000-output calibration stopped at the fourth call's reported `max_tokens` limit.
Cost-only reconciliation retained failure and settled 460,965 total microdollars,
with zero reservation and no retry/answer recovery. No passing calibration followed.


E102: The local service-enabled full suite at `8555fcf` finished with 2240 passed,
ten Windows skips and one allocation-test setup failure in 1435.70 seconds. Its
private driver created an allocation database without the required `delivery_eval_`
prefix; the constructor denied it before concurrency execution. The exact case
passed with a corrected dedicated PostgreSQL database in 3.76 seconds. All three
owned databases were dropped and absence verified. This scoped environment correction
does not rewrite the original failed full-suite result; E100 separately records
passing hosted full/service checks at the retained production source.

E103: Root integration of explicit prompt versions, read-only completed scoring
inspection and the pure lossless file-pool codec passed 149 focused tests in 78.63
seconds at `e09d5e1`. The codec is unwired: no request profile or historical context
changed. These controls neither authorize execution nor establish calibrated scoring.

E104: A fresh five-case v2-prompt calibration with a 6,000-output per-call limit
completed at reviewed source `5ca56d3`: five valid outputs and overall verdict matches,
four exact finding-map matches, one mandatory failure and zero observed false-ready.
It remains CALIBRATION_FAILED. All five operations settled for 572,270 microdollars,
27,109 input and 17,469 output tokens, with zero reservation and unchanged cached
recovery. A read-only fixed-code diagnostic reported one criterion mismatch without
case IDs, labels, findings or prose. No historical score or passing calibration follows.


E105: Root integration at `e56828d` passed 138 affected scoring/adjudication/inspection
tests in 47.72 seconds, with the one optional actual Docker case explicitly skipped
in this run. Current repository-specific protected paths now join fixed execution
controls when rejecting candidate edits. The owned adjudication adapter reconstructs
current actual runtime evidence while preserving hypothetical authored peer findings;
it supplies no adjudicator calibration. Independent review cleared both changes.
Ruff/format (303 files), mypy (97 sources) and diff whitespace checks passed.


E106: With the pinned owned-runtime Docker image configured, the adapter's actual
evidence scope passed 12 tests in 12.11 seconds (23 unrelated cases deselected),
including the real-container context case omitted in E105. Model responses were
not executed. All 398 local links across 102 Markdown documents resolved. These
scopes overlap E105 and do not establish live adjudicator calibration.


E107: [CI at `c9b8b03`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36505270760)
failed three store-isolation tests on each Python version, with 2353 passed and 87
skipped (419.34 seconds on 3.12, 300.69 on 3.13). Actual services passed 87 tests in
232.93 seconds; secret scanning passed. The new authority guard preceded the old
store-overlap check in isolated unit fixtures. Fix `1128dc8` moves that unchanged
storage guard before qualification reads and strengthens the tests to forbid those
reads. Independent review cleared it; 137 affected tests passed with one optional
Docker skip in 30.43 seconds. Failed CI remains retained, not rewritten as success.

E108: Explicit prospective protocol contracts at source `71ee9ae` preserve six v1
schema goldens and default serialization while dispatching tagged v2 throughout
allocation, candidate/scoring/semantic execution and current read-only consumers.
380 affected tests passed in 332.54 seconds with three integration cases deselected;
three later revocation controls passed separately. Independent review passed all 43
new tests in 23.84 seconds. Root integration at `932406f` passed 138 protocol/protection/
qualification tests in 35.26 seconds with one integration case deselected. These scopes
overlap. No historical campaign, passing calibration, new live grant or budget reset
is implied. See [protocol implementation](protocol-v2-implementation.md).

E109: The explicit v3 scorer prompt passed version/binding controls but its separate
live Opus 5 calibration remained failed: five valid outputs, five verdict matches,
four exact finding maps, one mandatory failure and zero false-ready. Its five settled
calls cost 574,790 microdollars with zero reservation and unchanged cached readback.
The [calibration record](semantic-calibration.md) preserves the exact evidence and
prior failures. No private finding/prose was used to modify expectations or validators.


E110: A separate Opus 5.5/v3/6,000-output owned final-scorer calibration at source
`3b2f679` passed all five exact finding maps and verdicts, with zero mandatory failures
and false-ready observations. All five operations settled for 365,540 microdollars
(28,670 input, 12,543 output), with no reservation or cached-recovery changes. A current
read-only concrete authority required passing evidence and succeeded with writes,
reservation and settlement forbidden. This exact configuration is calibrated for the
owned anchors; historical scoring, adjudicator calibration and held-out accuracy remain
unproved. See [the complete record](semantic-calibration.md).


E111: Separate [owned adjudication calibration](semantic-adjudication-calibration.md)
uses actual owned runtime contexts, unchanged hypothetical peers, exact controller-derived
peer references and a distinct purpose/spec/grant/account. Expectations remain separate;
readback reconstructs all receipts and cannot write. The author passed 47 controlled
cases and an actual Docker case with the current pinned image; independent review
passed 16 scoped cases. Root integration at `4951133` passed seven broker/projection/
expectation/read-only/concern cases in 106.53 seconds (41 deselected). Ruff/format
(308 files) and mypy (98 sources) passed. No live adjudicator calibration or historical
adjudication was executed by these controlled tests.

E112: [Hosted CI at `700fc45`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36506867142)
failed the CLI unqualified-task denial fixture on Python 3.12 (2464 passed, 88 skipped,
730.82 seconds). It reused the protected store as output, triggering the correctly earlier
disjoint-store guard. Fix `006477b` supplies separate stores and prohibits artifact reads;
104 CLI/qualification tests passed in 13.63 seconds with one optional Docker skip. Python
3.13's check annotation confirms cancellation at its 15-minute job ceiling; it has no complete
test result. Actual services passed 88 cases in 251.50 seconds, and secret scanning passed.
The quality job now permits 30 minutes without reducing tests or product runtime deadlines.

E113: [Explicit merge linkage](historical-merge-linkage.md), source `5406f9e` integrated as
`0689cc1`, implements [ADR-017](adr/ADR-017-explicit-first-parent-merge-linkage.md). The author
passed 144 affected cases, independent review passed 77 linkage cases in 17.73 seconds, and
root passed 121 merge/linkage/import/derived-input cases in 46.40 seconds. These scopes overlap.
V1 goldens and refusals remain preserved. No historical capture, rights grant or admission was
performed; non-Python derivation restrictions remain unchanged.

E114: The shared provenance-conditional adjudication prompt v2 at `c34c33e` preserves exact
v1 resolution and unchanged output schemas, peer judgments and expectations. Root passed five
broker/version controls in 131.01 seconds (46 deselected). Actual owned calibration v41 then
stopped on its first HTTP 400, with 218,940 microdollars reserved and unknown usage. One separate
schema-only diagnostic v42 reported HTTP 400/invalid request and allowlisted unsupported
`prefixItems` hints; its 136,664-microdollar reservation also remains. No output, calibration
pass, retry authority or zero-charge conclusion was inferred. Neither failed operation was
reissued. Provider wire compatibility needs correction before a new prospective frozen run.

E115: [Single-attempt composition](single-attempt-coordinator.md), source `6c06a7e` integrated
as `84413a8`, joins canonical allocation, A/B candidate production, deterministic execution and
two final scorers on the original account/deadline. The author passed 24 combined tests in
255.97 seconds plus two later focused negatives; independent review passed 16 cases in
150.19 seconds. These use actual stage APIs/broker/SQLite and controlled qualification,
calibration, semantic-context and sandbox fixtures. No actual historical execution, phase
promotion, adjudication or strict-success release claim follows from them.
Root integration passed ten complete-result/UNKNOWN cases in 103.28 seconds (16 deselected).

E116: A read-only metadata inventory of three protected evaluation SQLite files checked all
30 account counters against 207 operation rows, including reserved tokens: 9,044,553 settled
microdollars and 593,230 reserved across three unsettled rows. No account IDs overlapped across
files. This snapshot precedes v41/v42, reads no model outputs and makes no ledger writes. It is
neither a provider invoice reconciliation nor a complete product/campaign cost gate.

E117: On 2026-09-29, the owner supplied an ignored local Linear key. Actual `LinearClient`
queries verified workspace/team discovery, active owner membership and In Review state;
all returned connection pages were complete. The ignored local configuration now binds this
repository to those exact IDs and retains publication disabled. No provider mutation, issue
delivery, signed webhook or live handoff was performed by these read-only checks.

E118: [Anthropic fixed-tuple projection](anthropic-tuple-schema.md), source `d00caff`
integrated as `5d2e983`, changes only homogeneous fixed-tuple generation syntax. The author
passed 118 model/forecast/receipt tests and 29 final new controls; root passed those 29 in
2.25 seconds. Non-tuple wire/receipt goldens remain unchanged, invalid original cardinality
still fails locally, and old tuple receipts cannot bind to the new request. Current v38
initial-scorer required-pass readback succeeded with no mutations or calls after integration.
Ruff/format (316 files), mypy (99 sources), package build and committed secret scanning passed.

E119: Separate prospective [adjudicator calibration v44](semantic-adjudication-calibration.md#recorded-live-owned-calibration)
passed five valid/exact cases, dispute maps and merged verdicts, with zero mandatory failures,
false-ready or new concerns. Five operations settled for 380,444 microdollars (52,826 input,
8,457 output), with no reservation or cached recovery changes. Current required-pass readback
succeeded with artifact/account/checkpoint/reserve/settle writes forbidden and unchanged totals.
The original v41/v42 HTTP failures and reservations remain retained. This owned calibration
is separate from initial scoring and confers no historical spending or campaign authority.

E120: [Historical adjudication execution](semantic-adjudication-execution.md), source
`e0924ed` integrated as `adc3175`, reconstructs two sealed actual reviews and permits one
exact third operation under a private controller continuation. It retains the original
account/deadline, same frozen model, separate current v2 calibration and unchanged agreements.
The author passed 39 new cases, 79 prior regressions and two final-source smoke cases.
Independent review passed 19 cases in 253.98 seconds; root passed three selected cases in
65.12 seconds. Current concrete adjudication authority consumed passing v44 evidence with
writes forbidden and unchanged accounting. Tests use controlled provider transports and
substituted admission/calibration fixtures, not actual historical inputs or phase execution.

E121: [Linear-only ingress](linear-ingress.md), source `1bf4880` integrated as `94d83c5`,
passed 40 owned route/header/body/timeout tests and actual loopback/public negative checks.
One actual Issue-only webhook delivered controlled ticket PER-5 into PostgreSQL with one
workflow/start command and zero model operations at intake. A real non-content update plus
an exact hash-matched signed replay left two inbox receipts and still one workflow/command/
outbox record. No additional execution budget was created. The initial description-comparison
refusal made zero mutations and remains recorded. This proves bounded live intake/replay,
not durable ingress, provider-triggered retries, review-state handoff or GitHub delivery.

E122: Two controlled real Linear tickets passed actual Temporal planning. PER-5 reached
`NEEDS_CLARIFICATION` with one settled call (2,091 input/3,007 output tokens, 85,630
microdollars). PER-6 reached `PLAN_REVIEW` with five criteria and no questions; one settled
call used 2,466 input/2,101 output tokens for 64,855 microdollars. Both accounts have zero
reserved balance, and isolated workers stopped with absence verified. Exact revision-bound
plan artifacts remain private. No human approval, build, publication or status handoff is
inferred; see [the actual planning record](linear-ingress.md#actual-ticket-to-plan-checks).

E123: The subsequent read-only protected evaluation ledger inventory includes the retained
v41/v42 reservations and passing v44 calibration: three SQLite ledgers, 33 distinct accounts,
214 operations, 9,424,997 settled microdollars and 948,834 reserved across five unsettled rows.
Every account cost/token counter matched its operation rows, with no duplicate account IDs
across files. It read metadata only and made no ledger writes. This excludes product planning
and is neither provider invoice reconciliation nor a complete campaign cost gate.

E124: A bounded additional development metadata screen found three candidates across
validators and blinker, without admitting any task. The protected blinker PR 83 acquisition
stopped on a binary asset outside the text-only snapshot contract; separate bounded diagnosis
confirmed byte size/hash/type without exposing content. All refusals remain retained, with no
partial capture, model call, runtime operation or admission. See [the acquisition record](historical-development-attempts.md#additional-development-metadata-screen-and-acquisition-refusal).

E125: Temporary Linear test infrastructure was closed with tracked identities. Exactly one
webhook-disable mutation was confirmed by a fresh provider read. The verified tunnel/API/
gateway processes stopped, ports 18090–18092 had no listeners, and both planning workers
were absent. Original tickets, workflow plans, usage and zero-approval records remain retained.
Unrelated services were unchanged. Ongoing intake requires a durable replacement endpoint.

E126: [Hosted CI at `e00796e`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36510490919)
passed Python 3.12 with 2,639 tests and 88 explicit skips in 916.18 seconds. Actual services
passed 88 tests in 227.81 seconds; secret scanning passed. Python 3.13 retained one AST golden
failure, with 2,638 passed and 88 skipped in 888.13 seconds. Python 3.13's default dump omits
empty lists; the test now explicitly preserves the original representation where supported,
without changing the frozen hashes or production code. All 37 merge-linkage tests passed on
local Python 3.12 and 3.13 in 9.17 and 11.26 seconds respectively. Full fixed-head hosted
verification remains required; the earlier failed run is retained.

E127: [Hosted CI at `512854f`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36511984505)
passed all four required checks. Each Python version passed 2,639 tests with 88 explicit
skips; actual PostgreSQL/Temporal/Docker integration passed 88 tests in 254.24 seconds.
Secret scanning passed. This validates that exact commit, including the AST compatibility
fix; it does not certify later journal changes or close the remaining product/campaign gates.

E128: The [campaign journal](campaign-journal.md), source `f3b58c3` integrated as `7fdfacb`,
records every frozen ordinal, phase decisions, serial intents and retained observations in
separate SQLite storage. Review corrected initial fixture/field errors and added exposure
reconstruction, prior-development-use detection, family keys, journal identity/path binding,
event transition reconstruction and lost-ack authorization rechecks. All 45 owned journal
tests passed in 94.42 seconds; mypy checked 102 source files, Ruff/format passed for the new
files, and staged secret scanning passed. These tests use controlled qualification and
actual SQLite transactions; no historical task, model, runtime or campaign was executed.
The executor adapter, authoritative reports and numerical promotion composition remain open.
Root integration passed eight selected registration, concurrency, exposure and authorization
cases in 15.78 seconds. Full root Ruff/format (325 files) and mypy (102 sources) passed.

E129: A metadata-only development screen of pygtrie, orderedmultidict and funcy retained
unsupported archive/license-profile and change-profile exclusions. A bounded follow-up of
the three remaining linked funcy candidates found PR 96/issue 95 metadata-eligible, with
67 baseline files totaling 267,796 bytes. The follow-up made seven requests (96,635 bytes),
after 13 earlier requests (150,215 bytes). No source, patch or issue body was opened, no
model or repository code ran, and no rights, oracle, runtime or qualification decision was
inferred. Full-context feasibility and protected acquisition remain prerequisites.

E130: [Hosted CI at `e7c67ca`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36618308416)
passed all four required jobs, including the campaign journal. Python 3.12 passed 2,684 tests
with 88 explicit skips in 691.10 seconds; Python 3.13 passed the same counts in 609.81 seconds.
Actual PostgreSQL/Temporal/Docker integration and secret scanning passed. This proves that
commit's tested scope, not later changes or completion of the product and evaluation gates.

E131: [Completed semantic consumption](semantic-consumption.md), source `bd6c19e` integrated
as `94c9ebf`, reconstructs two initial reviews and an optional exact adjudication continuation
under current report permission. The original execution APIs and windows remain unchanged.
Root review added initial-review checkpoint rereads, a concurrent mutation refusal, explicit
v1 coverage, real executor-based adjudication fixtures with one dispute and preserved agreements,
and prefix/tail/current-authority denials. All 32 owned tests passed in 572.13 seconds.
Two final positive cases passed in 50.88 seconds with class-wide ledger/artifact writes forbidden;
candidate/scoring accounting and protected artifact bytes remained unchanged. Full Ruff/format
and mypy passed in the isolated source tree; staged secret scanning covered 79,107 bytes.
The cases exercise actual coordinator and broker APIs with controlled HTTP/SQLite, substituted
qualification/context/calibration admission, and no paid calls or historical source. They do
not establish historical accuracy, indefinite archival authority or a complete campaign report.

E132: The [completed-attempt reader](completed-attempt-reporting.md) composes the concrete
candidate, deterministic and semantic readers with the original coordinator binding,
stage terms, outcome, chronology and exact operation inventory. It retains early failures
and original costs; an adjudicated report preserves the initial outcome unchanged and
adds exactly the verified continuation's cost. Thirteen final-source controlled cases passed
in 200.53 seconds, including altered outcomes, current revocation during final reads and
cross-account result rejection. Two additional v1/A and v2/B cases passed in 28.64 seconds
after correcting a test-only assumption that allocation authorization carried the protocol
tag (the initial two failures remain retained). No production change was needed for that
fixture correction. Full Ruff/format (331 files), mypy (104 sources), wheel/sdist build and
450 local documentation links passed. Owned HTTP/SQLite and substituted admission/runtime
boundaries remain explicit; no historical campaign, paid call or aggregate promotion occurred.

E133: A bounded metadata-only screen of inflection, cached-property and markdownify made
nine requests (86,332 bytes), retaining missing-repository and unsupported-change exclusions.
It identified markdownify PR 264/issue 244 as metadata-eligible. A separate frozen acquisition
made 32 requests (237,736 bytes), capturing 24 files totaling 94,098 source bytes and deriving
two changed files, one relocated whole test file and one frozen acceptance selector.
It completed `DERIVED_NOT_IMPORTED`, with no model call, repository execution, rights grant,
worker export or qualification. Historical source, patch and oracle content stayed protected.
See [the acquisition record](historical-development-attempts.md#markdownify-development-acquisition).

The protected partial-context inventory measured 261,183 compact-JSON bytes across the
executable baseline/reference and oracle, without emitting contents or measuring a full model
context. Subsequent metadata-only screens made 20 requests (125,219 bytes), retaining six
unsupported changes and four further markdownify candidates. Those candidates remain
unacquired and unqualified; their metadata cannot establish independent task families.

E134: [Hosted CI at `96432d0`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36620914674)
passed all four jobs. Python 3.12 passed 2,716 tests with 88 explicit skips in 1,388.31
seconds; Python 3.13 passed the same counts in 709.83 seconds. Actual services passed
88 tests in 247.25 seconds; secret scanning passed. This includes semantic consumption.

E135: [Hosted CI at `c75822c`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36623838216)
passed all four jobs, including whole-attempt reporting. Python 3.12 passed 2,731 tests
with 88 explicit skips in 1,225.95 seconds; Python 3.13 passed the same counts in 1,231.33
seconds. Actual PostgreSQL/Temporal/Docker integration passed 88 tests in 252.89 seconds;
secret scanning passed. Later dispatch changes require their own final-head verification.

E136: Serial campaign dispatch passed 69 focused journal and execution tests in 334.65
seconds. The scope includes transactional exclusion across campaigns, a subprocess exiting
after committing a dispatch, concurrent controllers, cancellation, current-phase revocation,
optional exact adjudication and three lost-completion-acknowledgement boundaries. Completed
proof recovery forbids model, artifact and spending-ledger writes; incomplete proof retains
the active fence. Final Ruff/format (335 files), mypy (105 source files) and wheel/sdist build
passed. These owned SQLite/coordinator/controlled-HTTP tests substitute admission and runtime
boundaries; no paid call, historical campaign or incomplete-worker quiescence is established.
The change has root review, not an additional independent agent review. Exact-head hosted CI
remains required; phase execution, aggregates and numerical promotion remain open.

E137: The bounded phase driver passed 17 focused tests in 37.29 seconds. Sixteen use
real journal transactions with a substituted single-attempt boundary; one invokes the
concrete dispatcher/coordinator and controlled model broker for a known candidate failure.
The scope covers frozen phase order, bounded resume, intent-only recovery, active-dispatch
exclusion, original-authority pinning, expiry, stopped metadata and forged completion
acknowledgements. The driver does not promote phases or turn scheduling metadata into
scoring/accounting proof. Historical execution, aggregate reporting, complete preparation
costs, numerical gates and incomplete-worker reconciliation remain open.

E138: Metadata-only accounting and exact preparation inventories passed 26 focused tests
with actual SQLite and PostgreSQL in 2.10 seconds. Coverage includes consistent reads during
concurrent settlement, current guard denial, resource separation, unknown reservations,
missing accounts, counter corruption, inventory scope/term changes and forbidden writes.
Ruff/format (343 files), mypy (108 sources) and staged secret scanning passed. The reader
does not load model result payloads or establish complete campaign inventory coverage.

E139: At frozen source `47d739e`, a finite metadata-only capture reconciled 33 accounts and
214 operations from the three existing v52 evaluation ledgers. It preserved 209 settled
operations (9,424,699 model plus 298 infrastructure microdollars), five unresolved operations
and 948,834 reserved model microdollars. Before/after metadata matched; no ledger write,
model payload access, historical task execution or paid request occurred. Exact inventory
references and private metadata reports were retained. [The accounting record](campaign-accounting.md)
includes digests, token counts and explicit exclusions; this is not complete campaign cost
or provider invoice reconciliation.

E140: [Hosted CI at `f1d6d17`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36627522389)
passed all four checks. Python 3.12 passed 2,755 tests with 88 explicit skips in 1,630.99
seconds; Python 3.13 passed the same counts in 1,023.73 seconds. Actual service integration
passed 88 tests in 255.17 seconds; secret scanning passed. The phase driver was subsequently
pushed as `6b5179a` and requires its own hosted result. Later isolated accounting/reporting
changes are not covered by this dispatcher result.

E141: Prospective readiness policy pinning passed 15 focused tests in 27.26 seconds. The
preceding combined journal/dispatch/policy run retained 69 passes and one fixture failure
in 151.65 seconds: its foreign commit was identical to the original owned fixture commit.
The corrected fixture asserts a different value. Policy pinning now refuses
retrospective insertion, existing canonical accounts, changed policies and mismatched
campaign/commit/mapping data, and preserves original policy inspection without artifact writes.
All 55 existing journal/dispatch-journal checks passed in the combined run. This establishes
prospective rules and metadata behavior, not aggregate results or promotion.

E142: All-assignment reporting passed 16 focused tests in 115.46 seconds after adding
dispatch/account/completion chronology checks; the additional concrete false-ready case
passed in 19.88 seconds. Actual controlled coordinator/scorer proof covers failure, PASS,
FAIL and optional exact adjudication, with reporting effects forbidden. Missing assignments,
unknown reservations, primary/stability separation, preparation inventory costs, changed
state and revoked authority remain explicit. Three existing A/B dispatch and legacy v1
consumption checks passed in 61.88 seconds. These are owned fixtures with controlled HTTP
and explicit admission/runtime stand-ins, not historical campaign results or complete
program inventory proof. The CI quality-job limit increases from 30 to 45 minutes because
the last Python 3.12 dispatcher suite took 27 minutes before these additional scopes;
product/benchmark execution ceilings and all tests remain unchanged.

E143: [Hosted CI at `6b5179a`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36630852603)
passed all four jobs. Python 3.12 passed 2,772 tests with 88 explicit skips in 1,431.52
seconds; Python 3.13 passed the same counts in 1,293.65 seconds. Actual service integration
passed 88 tests in 262.61 seconds; secret scanning passed. This includes the phase driver.
The subsequent accounting/policy/aggregate-report changes require their own final-head CI.

E144: The full Windows suite at unchanged `6b5179a` completed with 2,762 passed and 98
explicit skips in 3,850.61 seconds. The skips include unavailable service configuration and
POSIX-only cases; this run is not service integration evidence. Earlier exact-head hosted
CI supplies its separately recorded service checks. The root checkout then advanced through
the four existing commits to `9c72b37` without altering their identities or merging PR #1.

E145: Whole-ledger census and report coverage passed a combined 61 accounting, preparation,
census and aggregate-report checks in 144.67 seconds, including actual PostgreSQL selected
and whole-ledger repeatable-read/read-only checks in disposable databases. After a final
compatibility adjustment and corrupt-unselected-account case, all nine coverage tests passed
in 19.47 seconds. Coverage includes omitted zero-cost/unknown accounts, duplicate account IDs
across ledgers, orphan operations, bounded-size refusal, concurrent settlement/account creation,
separate whole-ledger authority and changed scope during reporting. No historical source,
model-result payload, paid request or existing preparation ledger was consumed or changed.
Ruff/format (352 files), mypy (111 sources) and wheel/sdist builds passed. This verifies
coverage inside declared ledgers, not complete program-registry authority or cost promotion;
those remain open. Final-head hosted verification remains required.

E146: [Hosted CI at `9c72b37`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36634011617)
passed all four jobs. Python 3.12 passed 2,829 tests with 89 explicit skips in 1,709.94 seconds;
Python 3.13 passed the same counts in 1,340.42 seconds. Actual PostgreSQL/Temporal/Docker
integration passed 89 tests in 255.22 seconds; secret scanning passed. This verifies the
accounting, prospective readiness policy and all-assignment reporting changes at that commit.
The later ledger-census commit `1c0ba98` was pushed only after this run finished and requires
its own exact-head verification.

E147: Prospective phase statistics and version-2 completed-attempt metadata passed the final
combined 69 policy/statistics/whole-attempt/aggregate/ledger-coverage tests in 456.39 seconds.
Actual controlled coordinator/scorer/adjudication receipts establish acceptance/regression
booleans and original allocation/final checkpoint timing; current-authority denial paths
remain exercised. Arithmetic checks cover exact 60% boundaries, missing sealed-phase
independence, unavailable/unresolved assignments, paired denominator/order/seed behavior,
unknown costs, and stability repeats excluded from primary comparisons and task intervals.
The initial run retained 68 passes and one exact-float parity assertion failure in 477.89
seconds; the corrected comparison uses tolerance for 0.1 versus 0.09999999999999998.
An intermediate 28-case policy/statistics run passed before the final checkpoint/schema
adjustments; the final 69-case run covers all those changes. Ruff/format (355 files), mypy
(112 sources), package builds and staged secret scanning passed. These scopes overlap and
are not summed. No historical payload, paid execution, pilot decision or completed release
is established. Complete program registry/cost, criterion coverage, verified infrastructure
incidents and operational promotion remain open; final-head hosted CI remains required.

E148: [Hosted CI at `1c0ba98`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36637230360)
passed all four jobs. Python 3.12 passed 2,847 tests with 90 explicit skips in 1,751.73 seconds;
Python 3.13 passed the same counts in 1,372.67 seconds. Actual PostgreSQL/Temporal/Docker
integration passed 90 tests in 237.06 seconds; secret scanning passed. This verifies the
whole-ledger census extension. Later phase-statistics and requirement-inventory changes
still need their own exact-head hosted result.

E149: Prospective requirement inventories and their policy/report integration passed 66
combined inventory/policy/statistics/aggregate-report tests in 188.43 seconds. An additional
capture-permission revocation case passed in 5.90 seconds. The new inventory tests use owned
manifests with an explicit qualification/calibration stand-in and real artifact/journal
bindings. Coverage includes complete ordered task sets, manifest/qualification/registration
identity, invalid count sums/types, capture chronology, post-execution refusal, no partial
export on denial, retained legacy unknowns and unrun-task denominators without protected
context loading. Ruff/format (358 files), mypy (113 sources) and package builds passed.
No actual historical inventory, private answer access, paid call, criterion score or
promotion is claimed; complete criterion-evidence consumption remains open.


E150: The full local Windows suite at unchanged `1c0ba98` completed with 2,837 passed and
100 explicitly skipped tests in 3,651.55 seconds. This invocation did not configure service
integration environments; service and POSIX/symlink limitations remain explicit skips.
Hosted service evidence remains the separate E148 result. The root checkout was then
fast-forwarded, preserving the original phase-statistics and inventory commit identities,
to `7138173`. This Windows run does not verify later commits or criterion-judgment changes.


E151: [Criterion judgment reporting](criterion-judgments.md) now reconstructs content-free
semantic status counts through the concrete completed-semantic and whole-attempt readers.
It preserves agreements, unresolved/invalid judgments and separately counted adjudication
concerns; early candidate/deterministic failures have no semantic summary. Aggregate counts
match the frozen requirement inventory and retain unscored requirements for missing proof.
Manual-type automated judgments do not supply human approval; required evidence completeness,
operational/infrastructure/full-program-cost gates and promotion remain open.

The counts/statistics/inventory scope passed 50 tests in 52.76 seconds. The broader consumer,
whole-attempt and aggregate scope passed 60 tests with four setup errors in 782.76 seconds.
Those four owned fixtures incorrectly accessed `JournalRegistration.manifest_digest`; they
now read the frozen campaign's manifest digest. The corrected four actual aggregate cases
passed in 85.54 seconds, with production source unchanged. The original process had already
imported the prior fixture. Tests preserve actual controlled receipts and current-authority
checks, explicit qualification/calibration/runtime stand-ins and authored prospective owned
inventory metadata. Ruff/format (361 files), mypy (114 sources), package builds, 486 local
documentation links and staged secret scanning passed. New-head hosted CI and independent
review remain required. No historical payloads, paid calls, renewed grants or release success
are established by these changes.


E152: [Hosted CI at `7138173`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36640615411)
passed all four jobs. Python 3.12 passed 2,882 tests and 90 explicit skips in 2,112.07 seconds;
Python 3.13 passed the same counts in 1,486.86 seconds. Actual PostgreSQL/Temporal/Docker
integration passed 90 tests in 257.46 seconds; secret scanning passed. This verifies prospective
phase statistics and requirement inventories. Criterion judgments at `503ed5e` were pushed
only after this run finished and have their own subsequent hosted run.

E153: [Prospective program-budget envelopes](program-budget.md), under
[ADR-020](adr/ADR-020-prospective-program-budget-envelopes.md), now compose a shared registry
with new schema-2 evaluation ledgers. One transaction holds an account's maximum liability
before local creation. Model/infrastructure reservations require an ACTIVE envelope and OPEN
local account. Concrete irreversible closure and receipt-matched cost precede release of unused
capacity. Missing or unknown outcomes, partial creation/activation/closure, wrong targets,
revocation and malformed state cannot silently release or recreate capacity. Schema-1 ledgers
remain unchanged and cannot acquire coverage retrospectively.

The initial 64-pass/one-skip and expanded 123-pass/one-skip scopes were followed by 128 passing
registry, legacy accounting, metadata snapshot and allocation tests in 14.43 seconds, with
actual PostgreSQL and no skips. The tests cover concurrent cross-ledger admission, recovery,
closure/reservation races, shared infrastructure costs, identity/schema/counter denial,
readers without new-spending authority, and actual v1/v2 campaign allocator capacity checks.
Temporary PostgreSQL databases were removed and absence verified. These are owned fixtures;
no actual historical ledger was enrolled and no paid call, grant renewal or migration occurred.
Historical liability incorporation, campaign-required enrollment, complete program report
reconciliation and cost promotion remain open. Final hardening retains canonical budget terms and recomputes every envelope ceiling during
registry transactions, so an understated ceiling cannot create false available capacity.
The expanded 131-test scope passed in 15.84 seconds with PostgreSQL and no skips. Ruff/format
(365 files), mypy (115 sources), package builds and 494 local documentation links passed.
New-head full CI and independent review remain required; the registry does not authorize
execution or establish complete program cost.

E154: [Hosted CI at `503ed5e`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36644080109)
passed all four jobs. Python 3.12 passed 2,900 tests with 90 explicit skips in 1,731.71 seconds;
Python 3.13 passed the same counts in 1,389.19 seconds. Actual PostgreSQL/Temporal/Docker
integration passed 90 tests in 213.11 seconds; secret scanning passed. This includes criterion
judgment reporting. Later program-budget and reconciliation work needs its own exact-head CI.

E155: [Concrete program accounting reconciliation](program-accounting.md) now compares the
registry with every bound ledger's actual metadata, binding and local lifecycle state. One
read-only transaction per ledger captures the complete view; repeated ledger/registry reads
refuse changing facts without claiming a distributed atomic snapshot. Pending creation,
activation and closure retain full registry holds. Unexplained accounts, missing active
accounts, inconsistent costs/budgets/bindings and revoked scope refuse evidence. Campaign
reports can include the separate proof while preserving unrun assignments and unavailable
preparation inventory. No mutation, private model result read, promotion or spending authority
is supplied; historical liability and mandatory future enrollment remain open.

The combined reader/registry/accounting/coverage/campaign scope passed 84 tests in 140.21
seconds with actual PostgreSQL and no skips. The final focused scope passed 23 tests, with
17 deselected, in 13.86 seconds after three further registry-change/revocation/unenrolled-target
cases; production source was unchanged. Tests inspect PostgreSQL read-only repeatable-read
mode, preserve partial states, forbid result/checkpoint reads and mutation, and verify owned
database cleanup. Overlapping counts are not summed. Ruff/format (368 files), mypy (116
sources), and package builds passed. Exact-head hosted CI and independent review remain open.
No live historical ledger enrollment, paid call, grant renewal or release gate pass is claimed.
