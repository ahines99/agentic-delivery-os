# Historical candidate curation preparation

Status: **36 real source metadata candidates, zero qualified tasks, zero scored tasks**.
Prepared 2026-09-28; protocol revised the same day under
[ADR-007](adr/ADR-007-automated-benchmark-qualification.md) following the user's hands-off, fully agentic
benchmark preference. This advances M1-08/M5-01 preparation; it does not pass qualification or benchmark gates. The [evaluation methodology](evaluation-methodology.md)
remains normative: target 36/minimum 30, three repositories, grouped equal splits, a repository
reserved for sealed test, at least 24 behavioral tasks, and two independently executed agent qualification passes per admitted task,
with a distinct adjudicator for disagreements and unresolved findings failing closed. Baseline and accepted-solution checks each require three repetitions.

## Candidate sources and rights

[SWE-bench's official dataset guide](https://www.swebench.com/SWE-bench/guides/datasets/)
describes its historical Python task collections. We staged metadata from the official
[SWE-bench Verified dataset](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
at revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`. Upstream human verification does not
establish this project's tier/risk, licensing, runtime, relevance or scoring qualification.
Public familiarity also leaves contamination risk.

The [catalog](../evals/candidates/swebench-verified-36.json) contains 12 candidates each from
pytest, Sphinx and SymPy. Top-level licenses were fetched at every exact candidate base and
hashed: pytest MIT, Sphinx BSD-2-Clause, and SymPy BSD-3-Clause. Each record links its pinned
license evidence. Embedded components and file-specific exceptions require separate review.
The pinned [dataset card](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/blob/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/README.md)
does not declare a dataset license. Repository code licensing is not dataset or issue-text
authorization; all such usage decisions remain explicitly `PENDING`. Do not redistribute
dataset bodies or solution material on the strength of these metadata records.

Only `repo`, `instance_id`, `base_commit`, `created_at` and `version` were projected from the
source Parquet file. Acquisition used HTTP byte ranges for the Parquet footer and exactly those
column chunks, constructing an in-memory sparse buffer for PyArrow projection. Patch, test-patch,
problem-statement, hint and withheld-test-ID columns were not requested, read or stored.
The [metadata projection](../evals/candidates/metadata-projection.json) records these columns;
its byte digest is bound into the catalog. This is metadata-only research, not benchmark execution.
The derived JSON projection uses UTF-8/LF bytes so its digest is identical on Windows and Linux;
write those bytes explicitly when regenerating it, before updating the catalog digest.

Original issue URLs are absent from these projected columns. An instance ID's numeric suffix
must not be fabricated into an issue URL: task instances derive from issue/PR pairs. Consequently
`issue_url` is null and linkage is `PENDING`; source dataset revision plus `source_task_id` identify
the actual source record. The source creation timestamp is not asserted to be the original issue
creation time. Protected qualification agents must resolve and freeze pre-solution issue text in their protected workspace.

On 2026-09-28, a metadata-only GitHub GraphQL query found current closing-issue associations for
17 of the 36 candidate pull requests. The [linkage observations](../evals/candidates/issue-links.json)
record repository IDs, PR URLs/merge timestamps and issue URLs/creation timestamps only. No issue
bodies, solutions, commits, patches or hidden tests were fetched by this query. Current associations
do not establish historical wording or resolve rights, so catalog admission remains unchanged.
Reproduce the bounded read-only query with:

```sh
uv run python scripts/research_candidate_issue_links.py --catalog evals/candidates/swebench-verified-36.json --output /private/evaluation/issue-links.json
```

## Provisional selection and splits

The first 12 lexicographically sorted source IDs in each selected repository were staged. This
deterministic convenience selection is not random or representative, and it has not been screened
for difficulty, low risk, executable acceptance or supported environment. Reject unsuitable tasks
with recorded reasons and replace them before freeze; never quietly remove scored failures.

| Repository | Proposed split | Candidates |
| --- | --- | --- |
| pytest-dev/pytest | development | 12 |
| sphinx-doc/sphinx | validation | 12 |
| sympy/sympy | test | 12 |

These are **candidacies, not frozen splits**. Keeping repositories separate prevents same-repository
families crossing this proposal, but qualification agents must still identify related issues/backports and
cross-repository links. The sealed-test candidacy has exposed only identifiers/base metadata here,
not specifications or answers. Do not open its tasks during development or model selection.
Dataset source split `test` is upstream labeling and is distinct from our proposed three-way split.

### Development compatibility screen

A subsequent metadata-only [Git-tree screen](../evals/candidates/development-compatibility.json)
on 2026-09-28 found that **all 12 proposed development candidates exceed the current
full-source snapshot profile**: each pinned repository tree contains at least one
tracked file larger than 256 KiB. The complete, nontruncated trees contain 413–578
files, below the separate 1,000-file limit, and no links or submodules. All also
contain runner-package paths requiring separate compatibility review. No source,
issue, patch, oracle or held-out repository content was fetched by this screen.

These candidates are unsupported by the current profile; none was imported or
qualified. The original catalog and all observations remain retained. Before freezing
development tasks, the protected acquisition process must either find and record
supported replacements or validate an explicitly extended profile. Silently dropping
large files, slicing repositories or relabeling modified snapshots as complete is not
allowed. The 30-task, three-repository and held-out requirements remain unchanged.

Metadata research identified smaller replacement leads, and one subsequent protected
[baseline acquisition](historical-acquisition.md#recorded-public-baseline-acquisition)
captured all 43 text files of a pinned `tkem/cachetools` tree. No issue body, accepted
solution or oracle was fetched in that baseline run. Task-base selection, rights,
pre-solution requirements, reference/oracle mapping and full qualification remain
unresolved. It has not replaced or promoted any of the 36 original candidates.

The subsequent [protected derivation observations](historical-reference-derivation.md#subsequent-protected-development-observations)
retain a refusal for that cachetools candidate and a successful standalone derivation
for one `dbader/schedule` development lead. The latter remains unimported and
unauthorized for execution; no original candidate or split has been replaced.

## Offline staging and automated qualification worklist

```sh
uv run python -m agentic_delivery.evaluation.curation validate --catalog evals/candidates/swebench-verified-36.json --output .local/curation/validation.json
uv run python -m agentic_delivery.evaluation.curation worklist --catalog evals/candidates/swebench-verified-36.json --output .local/curation/worklist.json
```

Both commands are offline and deterministic, require no provider spend, and always report zero
qualified tasks. Validation rejects unknown fields (including answer material), fabricated
qualification states, mutable bases, mismatched license provenance, duplicate identities and
repository split crossings. It does not contact providers or independently validate license
interpretations. The worklist contains unanswered checks and empty review arrays; no
agent execution, human identity, vote or accepted task is invented. A schema/worklist alone is not
a completed qualification run. Output cannot replace the catalog input.

Copy the worklist into an evaluator-only workspace outside builder/reviewer-visible repositories
before adding protected evidence. Two distinct agent invocations independently resolve rights,
issue linkage, acceptance relevance, risk, environment, family grouping and leakage checks from the
same frozen inputs without seeing one another's verdict. The controller runs baseline acceptance/
regression qualification and accepted-reference qualification three times each in clean sandboxes;
model statements do not substitute for these receipts. Preserve model/config/input/output digests,
criterion-level evidence references, invocation IDs, usage and timestamps. A fresh third context
may adjudicate semantic disagreement after the initial records are sealed. Missing rights,
unsupported risk/runtime, failed deterministic checks or unresolved evidence remain blocked;
adjudication cannot manufacture authorization. Retain all disagreement/exclusion decisions.

Do not put historical patches, protected oracle tests, acceptance answers or filled qualification
worklists in this repository or campaign builder/reviewer context. Independent qualification and
scoring agents run in separate protected contexts with scoped authorized inputs. The user's change
removes human reviewer names as an admission prerequisite; it does not create past agent reviews,
qualified tasks, legal clearance, or authorization to spend beyond configured/authorized caps.

The staging `CandidateCatalog` is deliberately separate from `HistoricalTask`; it cannot be passed
as an admitted benchmark manifest and has no automatic promotion command. A later protected
qualification process must produce the protocol's full immutable machine-auditable evidence
before constructing the harness manifest and freezing a campaign. The current runtime manifest
is narrower than the full protocol; passing its schema alone does not satisfy the protocol.

## Validity, scoring and remaining work

The staged public tasks are diagnostic candidates, not an assumed-valid measurement of frontier
ability or human productivity. OpenAI's [Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)
reports flawed tests and contamination; its later [coding-evaluation audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/)
also withdraws its earlier recommendation of Pro (checked 2026-09-28). Switching benchmark names
cannot substitute for individual task validation. Prefer authorized, sufficiently recent alternative
historical tasks when these candidates cannot meet the unchanged criteria; do not lower risk,
rights, oracle or minimum-corpus requirements to promote this catalog.

After qualification, two separate evaluator-agent passes apply a development-calibrated frozen
rubric to each final candidate; deterministic acceptance/regression scoring is authoritative.
Disagreements require the recorded third-pass resolution or remain unsuccessful/unresolved. Agent
agreement, especially using one provider/model family, may contain correlated errors and does not
rule out memorization or malicious harness manipulation. The protocol retains contamination
controls, sealed-test isolation, matched budgets and zero-observed-false-ready promotion targets.

Human effort saved and review benefit remain unmeasured without actual people and observations;
never fill in fictional reviewer identities or human minutes. Human pilot signoff, plan approval
and human-only merge remain unchanged. Live GitHub App/Linear onboarding is still needed for product
integration proof; it is separate from agent-led local benchmark qualification. No qualified or
scored task is created merely by accepting this protocol revision.

## Current admission and historical inspection

Current `HistoricalTask` use requires `independent-agents-v2` and the concrete
in-process `QualificationAuthority`. The complete chain and current action grant
are revalidated for qualification, worker export, scoring or campaign freeze.
Synthetic-purpose records never authorize export/scoring/campaigns. Candidate
scoring additionally requires the separate budgeted `ScoringExecution` account and
rechecks authority before its metered operations. A prior admission result or a
serialized flag cannot substitute for this live authority.

The schema-1 contract below remains available through
`inspect_legacy_qualification()` and the explicitly named offline inspection CLI.
It describes historical evidence, grants no current use, and is never silently
upgraded. The offline CLI has no trusted authority loader and refuses current
`validate-qualification`/`freeze-campaign` requests. See
[campaign consumers](evaluation-campaign.md) for schema-2 registration and
[the evaluation workspace](../evals/README.md) for the current API boundaries.

The bounded `qualification.py` contract uses `QualificationRecord` with `schema_version=1`,
`qualification_mode=agent`, task/manifest identity, a `qualification_input_artifact`, exactly two
review-record artifact digests and an optional `adjudication_ref`. `QualificationInput` binds
rights/risk/runtime/leakage/family/oracle checks (`PASS`, `FAIL`, `PENDING`), environment and approved
acceptance/regression profiles, required node identities, and three repeated baseline/reference
execution records per suite. `AgentReview` receipts bind roles `qualifier_a`, `qualifier_b` and
optionally `adjudicator`, separate invocation/context IDs and actual model/input/output provenance.
Outputs declare `ADMIT`, `REJECT` or `UNRESOLVED` with evidence references. Any non-PASS deterministic
gate rejects historical inspection regardless of votes. Inspection returns status/reasons/digest, never solutions.

These hashes identify trusted-controller-owned record bytes; they do not authenticate arbitrary
artifact writers or prove that a named model actually ran. Keep artifact creation/access within
the trusted evaluator boundary and retain request/usage provenance. See implementation status for
executed tests; this document does not turn a supplied record into a real model qualification run.
This bounded qualification contract does not by itself implement campaign execution, calibrated
post-candidate dual-agent scoring or every normative provenance field.
