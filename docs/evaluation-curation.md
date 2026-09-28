# Historical candidate curation preparation

Status: **36 real source metadata candidates, zero qualified tasks, zero scored tasks**.
Prepared 2026-09-28. This advances M1-08/M5-01 preparation; it does not pass their human
qualification or benchmark gates. The [evaluation methodology](evaluation-methodology.md)
remains normative: target 36/minimum 30, three repositories, grouped equal splits, a repository
reserved for sealed test, at least 24 behavioral tasks, and two authenticated independent human
curators per admitted task. Baseline and accepted-solution checks each require three repetitions.

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
creation time. Curators must resolve and freeze pre-solution issue text in their protected workspace.

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
families crossing this proposal, but curators must still identify related issues/backports and
cross-repository links. The sealed-test candidacy has exposed only identifiers/base metadata here,
not specifications or answers. Do not open its tasks during development or model selection.
Dataset source split `test` is upstream labeling and is distinct from our proposed three-way split.

## Offline tools and human worklist

```sh
uv run python -m agentic_delivery.evaluation.curation validate --catalog evals/candidates/swebench-verified-36.json --output .local/curation/validation.json
uv run python -m agentic_delivery.evaluation.curation worklist --catalog evals/candidates/swebench-verified-36.json --output .local/curation/worklist.json
```

Both commands are offline and deterministic, require no provider spend, and always report zero
qualified tasks. Validation rejects unknown fields (including answer material), fabricated
qualification states, mutable bases, mismatched license provenance, duplicate identities and
repository split crossings. It does not contact providers or independently validate license
interpretations. The worklist contains unanswered checks and empty curator-review arrays; no
curator identity, vote or accepted task is invented. Output cannot replace the catalog input.

Copy the worklist into an evaluator-only workspace outside agent-visible repositories before
adding decisions or protected evidence. Two actual authorized maintainers must independently
resolve rights, issue linkage, acceptance relevance, risk, environment, family grouping,
qualification repetitions and leakage review. Retain disagreements/exclusions and their resolution.
Do not put historical patches, oracle tests, acceptance answers or filled qualification worklists
back into this repository or model context.

The staging `CandidateCatalog` is deliberately separate from `HistoricalTask`; it cannot be passed
as an admitted benchmark manifest and has no automatic promotion command. A later protected
qualification process must produce the protocol's full provenance and genuine human evidence
before constructing the harness manifest and freezing a campaign. The current runtime manifest
is narrower than the full protocol; passing its schema alone does not satisfy the protocol.
