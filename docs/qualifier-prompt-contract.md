# Qualifier prompt contract

The shared `qualifier_prompt` now explains the existing output validator's exact
requirements. This changes instructions and their fingerprint; it does not change
`ReviewOutputV2`, citation validation, semantic thresholds, expected decisions or
qualification authority.

The guidance enumerates the six eligibility IDs and requires one finding per exact
acceptance-criterion ID, without extra or duplicate targets. It maps each target to
its required inspected evidence, distinguishes snapshot line/node citations from
coordinate-free document/receipt citations, and explains calibration subjects'
additional document citations. It also states the existing initial/adjudicator
`resolved_disagreements` rules. Concerns belong in reasons or limitations rather
than invented finding targets.

No case identity, expected verdict or expected status map is inserted into these
instructions. Subject execution remains explicitly limited to the safe anchor.
Formatting compliance does not establish semantic correctness, and instructions do
not promise that a model will follow them. Validators continue to fail closed.

Surrounding rubric whitespace is normalized consistently with the context contract;
raw rubric size limits and artifact digests remain bound. Broker receipts bind the
actual resulting prompt digest. An earlier prompt artifact cannot satisfy the new
constructor merely because the rubric, output schema or expected outcomes are
unchanged. Completed earlier results and their accounting remain immutable, but
are not reinterpreted as current calibration.

The prior v8 live calibration remains a failed calibration. A separate live development stage with this prompt passed all five original cases,
with complete citations and unchanged expected findings. This is a small reused development
set, not evidence of general or held-out judge accuracy. Any future live stage
needs a newly frozen prompt/specification, current allowlist, distinct authorized
account and finite budget. Prior failures and costs remain retained. See [calibration records](evaluation-calibration.md#revised-prompt-passing-development-calibration)
for exact usage and retained earlier failures.

The targeted tests use the real structured broker and evaluation ledger with
controlled HTTP transports for both supported providers. They verify the actual
request and receipt prompt hashes, immutable cache reuse, pre-network rejection of
a stale specification, and rejection of completed prior-prompt evidence without
altering its artifacts, checkpoints or accounting. Existing target, citation,
subject and controller regressions remain the validation controls; no paid model
calls or real judge-quality claims follow from these tests.
