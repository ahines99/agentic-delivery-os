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

An optional `ledger_census_guard` separately authorizes metadata enumeration over the exact
sorted ledger identities supplied by the trusted controller. Without it, the report retains
`ledger_coverage_status=NOT_REQUESTED` and never broadens selected-account access. With it,
the report enumerates the execution ledger and every supplied preparation ledger before and
after reconstruction. Changed metadata invalidates the report; revoked census authority
cannot be swallowed as a successful partial result. Missing or corrupt census/preparation
evidence yields `UNAVAILABLE`, never complete coverage.

`OBSERVED` means the census was reconstructed and matched to concrete selected metadata.
Inspect `all_declared_accounts_covered`, `unaccounted_accounts`, and
`duplicate_account_ids` to determine whether all observed accounts are explained. Unknown
charges remain in census totals even when they are outside selected inventories. Future
unallocated canonical assignments stay missing in the assignment report; they do not make
the present ledger census incomplete. Coverage does not imply completed assignments,
settled costs, complete program-ledger selection, or promotion. Ledger snapshots retain
individual times and do not become a distributed atomic snapshot.

The report deliberately does not attest that the selected ledgers cover the entire preparation
program. Complete program inventory coverage, numerical and operational promotion, statistical
comparison, remaining time/criterion/regression metrics and human pilot signoff remain required.
Neither an empty queue nor a complete set of parsed rows authorizes a phase transition,
execution, pilot, merge or completed-campaign claim.

## Prospective phase statistics

New freezes pin the [phase statistics policy](adr/ADR-019-prospective-phase-statistics.md).
Reports with that original policy include phase-specific primary and stability summaries,
primary Wilson intervals, paired A/B success/cost bootstrap intervals, and resolved-pair
success discordances. Repeats do not enter primary comparisons or task-level intervals.
Earlier pinned policies remain readable with `phase_statistics=null`; the method cannot
be backfilled. Bootstrap seed and sample count are not caller-selected reporting options.

The version-2 whole-attempt consumption report now exposes its actual validated acceptance/regression booleans
and allocation-start/final-completion timestamps. Regression rates use only completed trusted
runs, with incomplete runs reported over all assignments. Candidate failures before scoring
have null scoring booleans. Timing summaries describe validated completed attempts and
include any exact adjudication tail; they do not silently infer timeout observations for
unfinished work. Functional acceptance here is deterministic acceptance, and stratum-specific
rubric/criterion coverage remains separate unfinished reporting work.
Original version-1 execution outcomes and grants are unchanged; the expanded consumption
report is freshly reconstructed metadata and does not replace those original artifacts.

Attempt cost summaries retain missing accounts and reservations. They exclude preparation
cost, which remains in the campaign-level accounting. Complete attempt cost requires every
assigned attempt's concrete proof, actual account and settled operations. Paired cost intervals
are explicitly conditional on both attempts having validated completion; unknown costs are
never zero-filled. Human effort and time savings stay unmeasured.

Individual per-arm numeric checks report `PASS`, `FAIL` or `INCOMPLETE`. Repeat strict-success
thresholds are `NOT_APPLICABLE`. An unrun sealed phase does not change validation's own
denominators or checks. Criterion coverage, infrastructure incidents, full program cost and
operational gates remain explicitly unavailable; numeric checks grant no phase or pilot authority.

An optional [prospective requirement inventory](campaign-criterion-inventory.md) supplies
complete per-arm requirement counts, including unrun assignments, grouped by verification
type. It must be pinned in the first reporting policy event. Its absence yields null counts;
reporting cannot backfill the inventory or load unstarted task contents to infer a denominator.
Counts alone do not close the criterion-coverage gate or supply passing/manual evidence.

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
