"""Stage metadata-only candidates for independent agent qualification; never admit tasks."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.evaluation.cli import write_json

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Repository = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
HTTPS = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$")]


class Candidate(Contract):
    id: NonEmpty
    repository: Repository
    base_sha: CommitSHA
    source_task_id: NonEmpty
    source_created_at: NonEmpty
    source_environment_version: NonEmpty
    issue_url: HTTPS | None = None
    issue_linkage: Literal["PENDING"] = "PENDING"
    repository_license_id: Literal["MIT", "BSD-2-Clause", "BSD-3-Clause"]
    repository_license_url: HTTPS
    repository_license_sha256: Digest
    repository_license_scope: Literal["TOP_LEVEL_ONLY_REVIEW_EXCEPTIONS"] = (
        "TOP_LEVEL_ONLY_REVIEW_EXCEPTIONS"
    )
    dataset_and_issue_usage_authorization: Literal["PENDING"] = "PENDING"
    proposed_split: Literal["development", "validation", "test"]
    family_review: Literal["PENDING"] = "PENDING"
    risk_review: Literal["PENDING"] = "PENDING"
    qualification: Literal["UNQUALIFIED"] = "UNQUALIFIED"

    @model_validator(mode="after")
    def verify_links(self) -> Self:
        license_prefix = f"https://github.com/{self.repository}/blob/{self.base_sha}/"
        if not self.repository_license_url.startswith(license_prefix):
            raise ValueError("License provenance must bind the candidate repository and base")
        if self.issue_url is not None:
            prefix = f"https://github.com/{self.repository}/issues/"
            if not self.issue_url.startswith(prefix) or not self.issue_url[len(prefix) :].isdigit():
                raise ValueError("Issue URL must identify an issue in the candidate repository")
        return self


class CandidateCatalog(Contract):
    schema_version: Literal[2] = 2
    status: Literal["UNQUALIFIED_CANDIDATES"] = "UNQUALIFIED_CANDIDATES"
    source_dataset: HTTPS
    source_revision: CommitSHA
    source_split: Literal["test"] = "test"
    source_dataset_license: Literal["NOT_DECLARED_IN_DATASET_CARD"]
    source_license_evidence_url: HTTPS
    metadata_projection_sha256: Digest
    metadata_columns: tuple[
        Literal["repo", "instance_id", "base_commit", "created_at", "version"], ...
    ]
    selection: Literal["FIRST_12_LEXICOGRAPHIC_IDS_PER_SELECTED_REPOSITORY"]
    split_status: Literal["PROVISIONAL_NOT_FROZEN"] = "PROVISIONAL_NOT_FROZEN"
    qualification_mode: Literal["independent-agents-v1"] = "independent-agents-v1"
    agent_passes_required_per_task: Literal[2] = 2
    candidates: tuple[Candidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_grouping(self) -> Self:
        if len({task.id for task in self.candidates}) != len(self.candidates):
            raise ValueError("Candidate IDs must be unique")
        if len({task.source_task_id for task in self.candidates}) != len(self.candidates):
            raise ValueError("Source task IDs must be unique")
        assignments: dict[str, str] = {}
        for task in self.candidates:
            if assignments.setdefault(task.repository, task.proposed_split) != task.proposed_split:
                raise ValueError("This staging design keeps each repository in one proposed split")
        return self


def load_catalog(path: Path) -> CandidateCatalog:
    return CandidateCatalog.model_validate_json(path.read_bytes())


def worklist(catalog: CandidateCatalog) -> dict[str, Any]:
    """Export unanswered curator work, with no fabricated identities or admission decisions."""
    return {
        "schema_version": 2,
        "status": "AWAITING_INDEPENDENT_AGENT_QUALIFICATION",
        "qualified_tasks": 0,
        "tasks": [
            {
                "candidate": task.model_dump(mode="json"),
                "agent_review_receipts": [],
                "pending_checks": [
                    "Identify original issue and freeze pre-solution requirements",
                    "Resolve dataset/issue usage authorization and repository license exceptions",
                    "Assess tier 0/1 eligibility and secret/service/runtime exclusions",
                    "Resolve duplicates, backports and related families before freezing splits",
                    "Pin environment, dependencies, commands and executable behavioral acceptance",
                    "Qualify baseline and accepted solution three times in protected workspace",
                    "Audit hidden-test relevance and leakage; retain protected evidence digests",
                    "Record two independent agent review receipts and adjudicate disagreement",
                ],
            }
            for task in catalog.candidates
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "worklist"])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.command == "worklist":
            result = worklist(catalog)
        else:
            result = {
                "schema_version": 2,
                "status": "METADATA_VALID_NOT_QUALIFIED",
                "candidates": len(catalog.candidates),
                "qualified_tasks": 0,
                "repositories": len({task.repository for task in catalog.candidates}),
                "proposed_split_counts": dict(
                    Counter(task.proposed_split for task in catalog.candidates)
                ),
                "split_status": catalog.split_status,
            }
        result["catalog_sha256"] = hashlib.sha256(args.catalog.read_bytes()).hexdigest()
        write_json(args.output, result, (args.catalog,))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["status"], "qualified_tasks": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
