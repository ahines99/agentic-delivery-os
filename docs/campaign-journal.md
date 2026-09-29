# Local campaign control journal

`CampaignJournal` records the frozen assignment order, current caller phase decisions,
execution intents and later observations in a dedicated local SQLite database. It is
separate from the evaluation spending ledger. It does not run a campaign, validate
outcomes, grant spending or decide whether promotion thresholds passed.

## Registration and authority

Construct the journal with an operator-owned path and the concrete execution ledger.
It rejects the ledger file itself, relative aliases, hard links, unexpected database
schemas, triggers and views. A persistent random journal identity and resolved path
bind every registration. Copying a populated journal to a different path is refused;
a fresh journal produces a different registration and cannot reuse existing grants.
Keep the approved journal path and its backup/recovery process under operator control.
The journal cannot discover exposure recorded in another unrelated registry or recover
deleted history. Losing the registry requires explicit reconciliation before execution.

`register_campaign(...)` reads the exact schema-3 frozen campaign and arm configurations,
reconstructs its schedule, corpus shape and caps, then binds task manifest/qualification
digests, provider case identities, execution-ledger identity, source commit, model
configuration references and preparation-account inventory. It atomically stores every
assigned ordinal, including work that has not been allocated or attempted. Repeating
identical registration is idempotent; changing the registration under the same campaign
identity is refused.

Provider repository IDs and issue node IDs are trusted caller metadata. The journal
does not query the provider or independently validate qualification, preparation-account
receipts, source checkout identity or costs. Current concrete proof readers remain
required by the executor and reporter. No source, oracle or model response is stored
in journal records.

## Ordering and retained observations

`open_phase(...)` accepts a current caller authorization binding the exact registration,
phase, decision artifact, policy and finite validity window. It rechecks the provider
before recording the decision. Development precedes validation, which precedes test;
advancing requires recorded dispositions for all preceding assignments. This ordering
check does not establish success, numerical promotion or permission to open a sealed set.
The trusted caller must independently validate the relevant decision before supplying
its phase authorization.

`claim_next(...)` uses a transactional sequence check and persists one next intent
before the caller may export source or start effects. Concurrent callers cannot claim
different ordinals while an earlier intent has no disposition. Retrying the exact intent
under its still-current authorization returns the original record, including a second
authorization check. It grants no permission to repeat its execution. Expired authority
cannot be renewed by changing the journal clock or creating a replacement intent.

`claim_dispatch(...)` adds a nonrenewable dispatch claim under the original current
phase grant. It permits only one unfinished dispatch across campaigns in this journal.
`finish_dispatch(...)` requires the matching outcome reference; its trusted caller must
validate that proof before asserting completion. Older journal readers reject these new
event kinds. Existing histories without dispatch events retain their metadata semantics.

`record_observation(...)` appends `STOPPED`, `UNKNOWN` or `OUTCOME_REFERENCE` metadata
with an evidence reference. It never fabricates an `AttemptOutcome`, classifies a stop
as an infrastructure incident, settles a reservation or creates another attempt account.
A later outcome reference can supplement an uncertain observation; it cannot erase the
original or replace an already recorded outcome reference. An active dispatch remains
fenced until `DISPATCH_FINISHED`; uncertainty or an outcome reference alone cannot release
the next assignment. Every assigned ordinal remains
in the registration. A caller must reconstruct the referenced proof before scoring it.

`inspect(...)` reads retained metadata, including after phase authorization expires.
It checks the registration, complete assignment inventory, event hashes and chronology,
phase/order transitions, exact intent bindings, observations and exposure index. Inspection
neither authorizes execution nor converts an observation into a validated result. Hashes
detect inconsistent records; they do not authenticate a malicious writer who controls the
entire journal and its authority providers.

## Sealed-set exposure

The first test intent atomically records a sealed-opening event and indexes every test
case before returning. Development and validation intents also retain their case exposure,
so moving a previously used case into a new test split does not make it unopened. Checks
use canonical repository URL/issue number, provider repository ID/issue number, provider
issue node ID and the declared family identifier. Changed campaign names cannot bypass
these recorded identities. Reconstructing the index from events rejects missing or
foreign exposure rows.

This detects exact identities and declared families within the pinned journal. It does
not infer semantic duplicates, detect arbitrarily renamed families, attest provider
metadata or prove that a case was never seen outside this controller. Those limits remain
part of corpus qualification and contamination reporting.

## Verification and remaining composition

Owned tests exercise actual SQLite transactions, concurrent registration/claims,
lost acknowledgements, current authorization changes, injected precommit exceptions,
phase ordering, retained uncertain outcomes, exposure rollback/reconstruction, prior
development use, registry copies and storage aliases. Corpus qualification is a controlled
fixture boundary. These tests make no model/provider/runtime calls and establish no
historical campaign result or actual process/host-loss recovery.

The [serial dispatcher](campaign-dispatch.md) now connects this journal to the concrete
single-attempt coordinator and optional adjudication. Whole-phase driving, all-assignment
reporting and numerical promotion remain open. The [completed-attempt reader](completed-attempt-reporting.md)
now reconstructs individual outcomes, failures and exact adjudication accounting under
current report authority. Journal observations alone cannot substitute for that proof. The existing
[single-attempt coordinator](single-attempt-coordinator.md),
[allocation](campaign-allocation.md) and independent scoring APIs retain their current
authorization, budget, deadline and receipt checks.
