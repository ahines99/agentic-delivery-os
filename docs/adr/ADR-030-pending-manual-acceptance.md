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

Remaining integration must bind a new manifest version to the complete assessed
criteria, retain all automated evidence, and expose pending manual criteria on the
draft PR. Publication admission and final readiness are distinct checks. Existing
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

Only the isolated candidate-engine portion is implemented so far. No new manual
publication or human-decision endpoint is currently installed or release-qualified.
