# Read-only completed semantic evidence

`validate_completed_semantic_consumption(task, authority=...)` reconstructs completed
initial reviews and an optional exact adjudication continuation under fresh, current
`campaign-report` permission. It does not renew execution permission, change a deadline,
invoke a model or write artifacts, checkpoints, operations or accounting.

The original execution readers keep their existing live-window contracts. The new
consumer distinguishes permission to inspect completed work from permission to perform
new work. Original completion timestamps must fall within the original grants, account
deadline and calibration validity. The consumer uses the actual current clock to check
reporting permission; it never evaluates an execution API with a fabricated past clock.

## Required authority

`CompletedStagesAuthority` supplies the concrete spending ledger, campaign/output stores,
current qualification authority, original candidate/allocation/scoring terms and current
candidate/scoring consumption providers. Both consumption purposes must be
`campaign-report`. Qualification still requires current campaign access for the candidate
reader and current scoring access for protected oracle reconstruction. Report permission
alone does not grant access to an oracle.

`SemanticConsumptionAuthority` adds the exact original semantic policy and concrete
calibration authority, current semantic context policy and separate report grant/policy.
The report grant pins the ledger, campaign ordinal/phase, allocation, task/qualification,
candidate/seal, deterministic evidence, initial result/plan, original grant/policy and
scorer calibration/configuration/prompt/schema/rubric. Its current window is at most
24 hours and contains no spending capacity. Policy and grant providers are checked again
after reconstruction.

Calibration remains the exact original evidence and must still pass its concrete current
validator. Its original sealed completion must precede the calls it supports, and its
original validity must cover those calls. A replacement passing calibration cannot
retroactively validate them. Expired or revoked original calibration, qualification or
data authority causes refusal. This API therefore supports inspection after an attempt's
execution window, not indefinite archival authority or inspection after every other
authorization has expired.

## Reconstruction and accounting

The reader first invokes the existing effect-free candidate and deterministic consumers.
A failed candidate or deterministic result cannot enter semantic success. It reconstructs
the semantic context from current admitted source/oracle and the exact sealed candidate
and deterministic receipts, then compares it to each saved context.

Each used initial operation must match its original forecast, prompt, configuration,
schema, output, immutable receipt and checkpoint chronology. Context and response
identities remain distinct. Finding structure, status, verdict and measured usage are
recomputed. Invalid reviews remain unresolved; agreeing model labels alone are insufficient.
The reader rechecks the initial role checkpoints after rereading the lower-stage chains.

The whole original account must close over the exact candidate, three deterministic and
used initial semantic operation IDs, plus the separately pinned adjudication operation if
present. Every operation must be settled and known; account totals, retained operation
reservations and original budget ceilings must agree. Missing, extra, RESERVED or UNKNOWN
operations cause refusal. Refusal is unavailable evidence, not a scored failure, zero-cost
result or permission to reissue work.

## Optional adjudication

An adjudication binding is all-or-none and requires a genuine valid initial disagreement,
the same frozen model, the exact separate concrete adjudicator calibration, original
adjudication policy/grant and one canonical operation on the original account. The reader
reconstructs both sealed peer claims, deterministic dispute references, shared v2 prompt,
unchanged agreements and merged result. Invalid resolutions remain unresolved; new
concerns cannot be silently promoted to success. Existing initial result bytes and their
original outcome are not replaced.

`ValidatedCompletedSemantic` returns the derived verdict, scoped strict-success flag,
exact operation receipt inventory and complete settled costs/tokens. Its version-2 output
also includes [criterion judgment counts](criterion-judgments.md), with invalid/disputed
criteria unresolved and valid adjudication concerns retained separately. It explicitly denies
execution authority, phase promotion and campaign completion. It does not establish that
the system declared readiness before final scoring, evaluate a whole-campaign threshold,
or measure human benefit. The separate [completed-attempt reader](completed-attempt-reporting.md)
composes initial outcomes and candidate/deterministic failures. The
[aggregate report](campaign-reporting.md) retains full assignment denominators and missing
proof; actual historical phase execution and release promotion remain open.

Owned tests use actual coordinator/scoring/adjudication APIs, controlled HTTP responses
and SQLite receipts. Qualification, protected context admission and calibration are explicit
fixture boundaries. They do not establish historical calibration, accuracy, actual Docker
execution or a completed campaign. Existing execution and current-authority requirements
remain unchanged.
