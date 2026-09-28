# Protected final semantic scoring contexts

`evaluation/semantic_scoring.py` implements read-only context reconstruction and
structural validation of proposed findings. It does not execute a scorer, calibrate
a model, authenticate a model result, resolve disagreements, or establish campaign
success. Existing qualification and deterministic scoring contracts remain unchanged.

## Current boundary

`assemble_semantic_context` requires a concrete current `QualificationAuthority`,
a concrete `CampaignScoringExecution`, a content-addressed candidate in the private
output store, and a trusted current allowlist of rubric artifacts. The separate
`validate_completed_scoring` API must reconstruct the existing versioned campaign
scoring chain: its immutable attempt/scoring checkpoints, current grants and policy,
settled metered operations, and exact candidate-bound collector evidence. Missing,
unknown, malformed, or functionally failing evidence prevents context construction.
This path creates no accounts, checkpoints, reservations, artifacts, or sandbox work.

The assembler revalidates current qualification, the rubric allowlist and completed
scoring evidence after reading artifacts. `validate_semantic_context` repeats that
reconstruction; a serialized context or its hashes alone confer no authority.
Private stores must remain disjoint from configured repositories and worker roots.
The caller owns the trusted policy providers and private storage boundary.

Each initial scorer receives the original source, exact frozen candidate, derived
diff, captured task requirements, frozen oracle, and normalized observed test nodes
and phases. Plain source strings preserve leading whitespace, trailing bytes and
line coordinates. The context binds the task/qualification/candidate, original
campaign attempt, shared account, scoring checkpoint, deterministic evidence and
individual receipt digests. Raw stdout, stderr, tracebacks and arbitrary report
extensions are omitted.

The context excludes the reference patch/snapshot and computed protected reference
closure, qualification judgments, calibration expected answers and builder/reviewer
judgments. Known forbidden digests cannot become rubrics; JSON object/array rubrics
are refused to prevent structured evidence aggregates being repurposed as prose.
This is not a semantic leakage detector: the trusted rubric author must not copy
protected answers into newly authored text. Hashes bind trusted artifact writers;
they are not remote authenticity attestations.

## Findings and citations

`SemanticScoringOutput` requires exactly one finding for every acceptance criterion
and each of `harness_integrity`, `hardcoding`, and `requirement_gaps`. Findings use
`PASS`, `FAIL`, or `UNRESOLVED`; the overall verdict is `FAIL` if any finding fails,
otherwise `UNRESOLVED` if any remains unresolved, otherwise `PASS`.

Every finding cites candidate file lines. Criterion and requirement-gap findings
also cite oracle lines and an acceptance node observed in the included receipt.
Harness findings cite the original source and both acceptance/regression receipts;
hardcoding findings cite the original source and oracle. File coordinates and node
IDs must exist in the included evidence. Duplicate/unknown targets, missing findings,
unknown artifact references, invalid coordinates, and incoherent verdicts fail closed.
These checks establish coverage and structure, not the truth of a model's reasoning.

Initial contexts use separate `scorer_a` and `scorer_b` stage/context identities and
contain no peer output. This module does not allocate independent model operations
or prove those contexts were independently executed. `scoring_adjudicator` is reserved
and denied until a later executor supplies authenticated sealed scorer receipts.

## Purpose and remaining work

Current reconstruction supports only `HISTORICAL_CANDIDATE`. The explicit
`OWNED_DEVELOPMENT_CALIBRATION` purpose is reserved and rejected by these validators;
owned ambiguous calibration subjects must use a distinct deterministic-evidence
adapter, never a falsely admitted historical task. Historical validation/test tasks
cannot become development calibration merely by changing this field.

A subsequent slice still needs an executed, budgeted development calibration;
current prompt/schema/config/rubric binding; two separately metered scorer receipts;
disagreement handling; and a final result combining deterministic and semantic
evidence without bypassing either. Context construction authorizes none of those
effects. No benchmark score, human-benefit measurement, or readiness claim follows
from this module.

## Verification

Owned tests cover exact byte/line preservation, complete target coverage, citation
and verdict failures, rehashed candidate/context substitution, expired authority,
rubric revocation, reference exclusion, absence of raw logs, sanitized exceptions,
and read-only reconstruction. Assembly isolation tests use the genuine controlled
qualification authority with the completed-scoring boundary explicitly replaced by
a fixture; those cases do not claim actual Docker scoring or semantic calibration.
A separate boundary test consumes the concrete completed-scoring reader and real
SQLite accounting after controlled harness execution, refusing account creation,
checkpoint writes, reservations and Docker construction during the read. That fixture
explicitly substitutes qualification admission and container results. These complementary
tests do not constitute a complete historical campaign or a calibrated semantic run.
