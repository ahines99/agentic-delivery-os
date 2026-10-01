"""Read public GitHub issue-link metadata without fetching problem text or solutions.

Uses the operator's gh session for read-only research, never as a product publisher.
An association is a curation lead, not proof of pre-solution requirements or eligibility.
"""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agentic_delivery.evaluation.cli import file_digest, write_json
from agentic_delivery.evaluation.curation import load_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_catalog(args.catalog)
    if len(catalog.candidates) > 100:
        parser.error("Research query is bounded to 100 candidates")
    fields = []
    for index, task in enumerate(catalog.candidates):
        owner, repository = task.repository.split("/")
        prefix = task.repository.replace("/", "__") + "-"
        number = task.source_task_id.removeprefix(prefix)
        if not task.source_task_id.startswith(prefix) or not number.isdigit():
            parser.error("Source task ID cannot be mapped to a candidate pull request")
        fields.append(
            f"r{index}: repository(owner:{json.dumps(owner)},name:{json.dumps(repository)}) {{"
            f" databaseId pullRequest(number:{int(number)}) {{ number url mergedAt "
            "closingIssuesReferences(first:100) { totalCount nodes { number url createdAt } } } }"
        )
    response = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=query {" + " ".join(fields) + "}"],
        capture_output=True,
        timeout=90,
        check=False,
    )
    if response.returncode:
        parser.error("Read-only metadata query failed; no result written")
    payload = json.loads(response.stdout)
    if payload.get("errors"):
        parser.error("Metadata query returned errors; no partial result written")
    records = []
    for index, task in enumerate(catalog.candidates):
        repository = payload["data"][f"r{index}"]
        pull = repository["pullRequest"] if repository else None
        links = pull["closingIssuesReferences"] if pull else None
        records.append(
            {
                "task_id": task.id,
                "repository_id": repository["databaseId"] if repository else None,
                "pull_request_url": pull["url"] if pull else None,
                "merged_at": pull["mergedAt"] if pull else None,
                "linked_issues": links["nodes"] if links else [],
                "links_complete": bool(links and links["totalCount"] == len(links["nodes"])),
                "qualification": "UNQUALIFIED",
            }
        )
    write_json(
        args.output,
        {
            "schema_version": 1,
            "kind": "public-candidate-issue-link-research",
            "catalog_sha256": file_digest(args.catalog),
            "observed_at": datetime.now(UTC).isoformat(),
            "source": "GitHub GraphQL pullRequest.closingIssuesReferences",
            "limitation": (
                "Current linkage alone does not freeze historical issue text or usage rights"
            ),
            "records": records,
        },
        (args.catalog,),
    )
    print(
        json.dumps(
            {
                "status": "METADATA_ONLY",
                "candidates": len(records),
                "with_linked_issues": sum(bool(record["linked_issues"]) for record in records),
                "qualified_tasks": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
