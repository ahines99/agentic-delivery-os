# ADR-030: Draft publication with pending manual acceptance

Status: implementation in progress, 2026-09-30. Completes the manual-criterion
requirement in M3-03/M3-04 and refines ADR-006's prepublication evidence gate.

Explicit manual criteria must not be replaced by pytest or a model's approval.
The product should nevertheless deliver the implementation and passing automated
checks as a draft for the authorized human to inspect. Until that decision exists,
the workflow cannot reach HUMAN_REVIEW or perform the Linear review-state handoff.

The product candidate profile may explicitly enable manual criteria. Automated
criteria retain their test mappings, isolated execution and independent review.
Manual criteria have no test mapping and must receive UNKNOWN from the model;
a model PASS is not human evidence. A successful automated portion returns
MANUAL_REVIEW_PENDING with the exact pending criterion IDs, never REVIEW_APPROVED.
The default shared candidate engine and historical evaluation profiles continue to
reject manual criteria. This does not change frozen evaluation conditions.

Manifest version 2 binds the complete assessed criteria, retains all automated
evidence, and exposes pending manual criteria on the draft PR. Publication admission
requires an explicitly enabled pending-manual profile; final readiness additionally
requires human decisions. Existing
v1 manifests retain their all-automated meaning; no missing field implies approval.

An authenticated reviewer submits an explicit decision covering the complete manual
criterion set. The durable command binds repository, base/head, manifest, input,
policy and configuration, using the existing command identity and actor authority.
The workflow revalidates authority and expiry when consuming it and before final
handoff. Models and automation cannot submit this human decision. Missing, failing,
stale, expired or revoked decisions block readiness. Required CI is still checked
against the exact published revisions after manual acceptance. Human merge remains
separate and mandatory.

The wait must be bounded and cancellable, use a workflow version marker for replay,
and retain the draft and explicit outcome on rejection or expiry. The PR evidence
must reflect confirmed acceptance before the Linear handoff. API, workflow,
publication, revision-race and actual storage/orchestration tests are required
before enabling this path in the installed service.

The candidate engine, pipeline, v2 manifest validator and draft publisher are
implemented. The product workflow opts into the new profile under its version marker;
default engine calls and historical evaluation retain their existing behavior.
The manual pipeline case separately passed using the installed pinned Docker
image and controlled model responses. Its actual baseline, candidate and automated
criterion receipts passed the v2 reference validator while the manual criterion
remained pending. Controlled GitHub transport tests retain one draft PR across retry;
they are not live provider or human-acceptance evidence. Ruff, formatting and mypy pass.

The authenticated API now exposes the current binding at
`GET /workflows/{id}/manual-review` and queues a complete decision at the corresponding
POST route. GET requires repository read access; POST requires operator and reviewer
roles. A queued receipt is not an applied acceptance decision. Persisted decision
consumption rechecks current reviewer scope, expiry and the complete bound evidence;
automation identities, partial/duplicate criterion sets and conflicting applied
decisions are refused. Owned SQLite/artifact tests cover restart, stale bindings,
revocation, expiry and authenticated API idempotency, not real human acceptance.

The durable wait and workflow command consumption are now connected under a Temporal
version marker. Eight actual PostgreSQL/Temporal cases passed: acceptance, rejection,
cancellation, timeout, stale-then-current decision, revoked reviewer, worker restart
while waiting and an uncertain final update. All eight histories replayed. Candidate,
CI and publication responses in those cases are scripted; no real human is impersonated.

The final evidence update preserves the draft and surrounding notes, checks current
revisions and uses a repository-scoped Pull requests write token. One read-back can
confirm a lost response without repeating PATCH. Current human/plan/CI checks run
before and after the provider effect. The Linear handoff requires the confirmed
acceptance artifact and revalidates the exact persisted decision. Unknown outcomes
retain an acceptance/result artifact and block the handoff. See the
[operator flow](../manual-acceptance.md) for the authenticated API and recovery limits.

The combined product/manual regression selection passed 270 tests with six explicit
Docker skips. The eight service cases separately passed in 32.09 seconds against a
disposable PostgreSQL database and the local Temporal server; the live database was
not used. Ruff, formatting and mypy passed. Full new-source regression/CI and
installation remain pending. This is not a completed release or human pilot gate.
