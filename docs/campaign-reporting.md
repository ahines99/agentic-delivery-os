# Current all-assignment reporting

`generate_campaign_report(...)` reconstructs a report for every ordinal of a registered
execution campaign. Its trusted `CampaignReportContext` supplies the exact journal and
artifact stores, selected preparation ledgers, a current report guard and a factory for
concrete completed-attempt consumption authority. It grants no execution permission.

The report requires the original [prospective readiness policy](adr/ADR-018-prospective-readiness-reporting.md).
It reads the frozen schedule and journal, then captures [accounting metadata](campaign-accounting.md)
for every canonical assigned account. Missing accounts remain explicit. The completed-input
factory is called only for finished dispatches; unstarted, active or merely observed ordinals
cannot trigger protected task loading through this API. An outcome reference without a
finished dispatch is not independently validated result proof.

## Concrete result consumption

Each finished dispatch is consumed through the actual [whole-attempt reader](completed-attempt-reporting.md).
That reader retains its current qualification, calibration, report permission and exact
original receipt requirements. The aggregate reader additionally matches campaign, ordinal,
task, phase, arm, task-manifest digest, outcome reference, canonical account, exact operation
IDs and settled cost/token counters. A mismatched or unavailable result becomes an explicit
unavailable row, without an invented FAIL verdict, zero-cost account or retry.
The dispatch must precede canonical account creation and completion, and every operation
must settle before the dispatch-finished event. Late journal records cannot retrospectively
establish that already-completed work was properly dispatched.

The original candidate status supplies its declaration through the frozen policy; final
scoring never supplies that declaration. A validated early candidate failure retains its
FAIL outcome, original known costs and false readiness declaration. A candidate declared
ready with a final FAIL is confirmed false-ready. An unresolved final verdict remains
unresolved; it cannot establish a clean false-ready gate.

Every consumed result is validated again before returning. Selected preparation inventory
metadata is reconciled twice. Changed accounting, journal events, reporting policy or revoked
current permission makes the aggregate report unavailable. These checks detect changes observed
during reconstruction; they do not establish a distributed atomic snapshot or defend against a
malicious owner who controls the stores and authorization providers.

## Denominators and cost scope

Each phase/arm has separate primary and stability summaries. Strict-success denominators
contain all its frozen assignments, including rows without usable proof. Known validated
failures, unresolved verdicts and unavailable outcomes remain separate counts. Readiness
unknowns and unresolved ready candidates prevent complete false-ready evidence. The observed
false-ready rate is null when no ready candidate has been validated; partial observed rates
are accompanied by their incompleteness counts and cannot serve as release claims.

Attempt accounting includes every existing canonical account, even if its scoring proof is
unavailable. The exact registered preparation inventories supply additional selected costs
when they can be reconciled. Missing preparation proof is labeled `UNAVAILABLE`; observed
attempt totals remain a partial sum rather than a claim of zero preparation spend. Reserved
and settled model/infrastructure costs remain distinct, including retained uncertainty.

The report deliberately does not attest that the selected ledgers cover the entire preparation
program. Complete program inventory coverage, numerical and operational promotion, statistical
comparison, remaining time/criterion/regression metrics and human pilot signoff remain required.
Neither an empty queue nor a complete set of parsed rows authorizes a phase transition,
execution, pilot, merge or completed-campaign claim.

## Verification

Sixteen focused checks passed in 115.46 seconds after the chronology guard was added;
the additional concrete false-ready case passed in 19.88 seconds. Coverage includes empty
and incomplete schedules, primary/stability denominators, unknown reservations, exact
preparation costs, changed journals/accounts, revoked report authority, mismatched proof
and late dispatch records. Concrete controlled coordinator/scorer receipts cover early
failure, semantic PASS, semantic FAIL and exact adjudication, with model/artifact/ledger
mutations forbidden during reporting. Adjudication preserves the original unresolved
outcome while reporting the validated final PASS and full known costs.

Three existing A/B dispatch and legacy v1 consumption checks then passed in 61.88 seconds.
Only owned fixtures are involved: qualification, calibration and runtime admission retain
their explicit stand-ins; provider HTTP responses are controlled. No historical campaign,
paid call, aggregate efficacy claim or pilot promotion is established by these tests.
