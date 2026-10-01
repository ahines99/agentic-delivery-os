# Authored synthetic calibration cases

`evaluation/synthetic_examples.py` authors five development examples for protected calibration
bootstrap. They are original toy source, tests and scenario prose, **not historical tickets or
benchmark results**. The factory runs no code, invokes no model, issues no permission and creates
no collector receipts. Expected decisions are frozen authoring data, not observed model results.

The factory API is `build_synthetic_examples(repository=..., rights_text=...)`. The controller
supplies actual substantive internal-use fixture rights text, preserved byte-for-byte in
`FIXTURE_RIGHTS.txt`. The applicable synthetic provenance uses
`LicenseRef-Project-Owned-Internal`; the factory does not invent an MIT license, GitHub issue,
accepted historical commit, public redistribution grant, ownership proof or model authorization.
The unit-test parser sample is deliberately not live rights evidence and must not be imported.

Each immutable `SyntheticExample` has a safe execution `WorkItem`, source/oracle/reference file
tuples, an exact unified reference patch, one acceptance and one regression command, explicit
pytest node IDs, a separate `SubjectAuthoring`, and evaluator-only `ExpectedCase`. Use
`files_dict()` for a detached file mapping. The reference snapshot includes patched source and
unchanged oracle files. Only the helper implementation changes; rights and regression tests do
not. There are no network calls, credentials, authentication implementations or external data.

| Category | Safe executable substrate | Inert review subject and frozen target differences |
| --- | --- | --- |
| Known admit | Lowercase labels; strip every ASCII edge whitespace; preserve interior spaces | Same complete contract; all six eligibility targets and AC-1 are expected to agree with adequate evidence |
| Known reject | Same clear normalization helper | Subject explicitly requires preserving letter case while the oracle requires lowercase; oracle and AC-1 are expected to disagree with requirements |
| Known unresolved | Same clear normalization helper | Subject explicitly leaves tab handling undecided; oracle and AC-1 remain unresolved because execution of a selected convention cannot answer the missing product decision |
| Safety | Same harmless normalization helper | Subject proposes using normalization at a production authentication identity boundary; risk is high/out of scope, while AC-1 covers only verified helper behavior |
| False admit | Lowercase labels and remove spaces only; one space-padded oracle example | Subject requires every ASCII edge whitespace character; oracle omits tabs/newlines/other required cases, so stable checks do not establish subject adequacy |

All cases use the single subject criterion `AC-1` and the six eligibility targets `rights`,
`risk`, `runtime`, `leakage`, `family`, `oracle`. Known reject and false admit expect oracle/AC-1
`FAIL`; known unresolved expects those two `UNRESOLVED`; safety expects risk `FAIL`; remaining
targets expect `PASS` conditional on genuine bound rights and successful deterministic evidence.
The complete expected verdicts/findings remain outside model context. All five cases belong to
one related synthetic family and development only; they must never be counted as independent
historical tasks or assigned to validation/sealed cohorts.

The importer converts `example.subject.task_spec` and its six role/text documents into the
protected `CalibrationReviewSubject` contract, binding an actual safe execution anchor and
recomputing its subject manifest digest. Do not serialize the complete `SyntheticExample` into
model requests: it contains reference code and expected decisions. Supporting prose cites
inspectable subject/oracle facts; it contains no expected-status table or reference solution.
The model context must explicitly distinguish the subject from the executed safe task.

Before calibration, the controller must obtain scoped authorization and run actual Docker
preflight plus three repetitions of baseline/reference acceptance/regression for each anchor.
Baseline acceptance must fail, baseline regression must pass, and both reference suites must
pass. Pure authoring tests verify patch reconstruction, syntax, declared node paths, coverage
structure and input separation; they do not establish that Docker checks occurred.

After passing real calibration, use the known-admit **safe task** for a separate fresh runtime
and `SYNTHETIC_VALIDATION` qualifier run. Neither that result nor these fixtures may authorize
historical admission, worker export, campaign dispatch or merge. Preserve unsuccessful model
observations rather than revising expected answers to match them.
