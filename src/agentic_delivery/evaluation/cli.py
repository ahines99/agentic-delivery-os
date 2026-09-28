"""Offline manifest/schema/report tools; never runs models or benchmark candidates."""

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from agentic_delivery.evaluation.campaign import (
    ArmConfiguration,
    CalibrationEvidence,
    CampaignSpecification,
    freeze_campaign,
)
from agentic_delivery.evaluation.comparison import ArmAssignment, compare_trials
from agentic_delivery.evaluation.harness import HistoricalTask, Trial, load_manifest, report
from agentic_delivery.storage.artifacts import ArtifactStore


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, Any], inputs: tuple[Path, ...] = ()) -> None:
    """Write deterministic JSON atomically, without replacing an input file."""
    if path.resolve() in {source.resolve() for source in inputs}:
        raise ValueError("Output must not overwrite an input file")
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-manifest", help="Validate historical-task JSONL")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    admission = commands.add_parser(
        "validate-qualification", help="Verify protected evidence for every task; no model calls"
    )
    admission.add_argument("--manifest", type=Path, required=True)
    admission.add_argument("--artifacts", type=Path, required=True)
    admission.add_argument("--output", type=Path, required=True)
    schema = commands.add_parser("schema", help="Export the actual Pydantic JSON schema")
    schema.add_argument(
        "--kind",
        choices=["historical-task", "trial", "campaign", "arm-configuration", "calibration"],
        required=True,
    )
    schema.add_argument("--output", type=Path, required=True)
    summarize = commands.add_parser("report", help="Report recorded trials; does not run tasks")
    summarize.add_argument("--manifest", type=Path, required=True)
    summarize.add_argument("--trials", type=Path, required=True, help="JSON array of Trial records")
    summarize.add_argument("--arm", choices=["A", "B", "C"], required=True)
    summarize.add_argument("--split", choices=["development", "validation", "test"], required=True)
    summarize.add_argument("--synthetic", action="store_true", help="Label synthetic control data")
    summarize.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare", help="Paired descriptive statistics; no scoring")
    compare.add_argument("--manifest", type=Path, required=True)
    compare.add_argument("--trials", type=Path, required=True)
    compare.add_argument("--arms", choices=["A", "B", "C"], nargs="+", required=True)
    compare.add_argument("--split", choices=["development", "validation", "test"], required=True)
    compare.add_argument("--seed", type=int, default=0)
    compare.add_argument("--bootstrap-samples", type=int, default=2000)
    compare.add_argument("--synthetic", action="store_true")
    compare.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser(
        "freeze-campaign", help="Preregister qualified tasks; never execute"
    )
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--specification", type=Path, required=True)
    freeze.add_argument("--artifacts", type=Path, required=True)
    freeze.add_argument("--output-artifacts", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            contracts: dict[str, type[BaseModel]] = {
                "historical-task": HistoricalTask,
                "trial": Trial,
                "campaign": CampaignSpecification,
                "arm-configuration": ArmConfiguration,
                "calibration": CalibrationEvidence,
            }
            write_json(args.output, contracts[args.kind].model_json_schema())
        else:
            tasks = load_manifest(args.manifest)
            manifest_digest = file_digest(args.manifest)
            if args.command == "freeze-campaign":
                if not args.artifacts.is_dir() or not args.output_artifacts.is_dir():
                    raise ValueError("Both artifact directories must already exist")
                destination = args.output.resolve()
                if (
                    destination.is_relative_to(args.artifacts.resolve())
                    or destination.is_relative_to(args.output_artifacts.resolve())
                    or destination in {args.manifest.resolve(), args.specification.resolve()}
                ):
                    raise ValueError("Summary must remain outside inputs and artifact stores")
                specification = CampaignSpecification.model_validate_json(
                    args.specification.read_bytes()
                )
                campaign, digest = freeze_campaign(
                    tasks,
                    specification,
                    ArtifactStore(args.artifacts),
                    ArtifactStore(args.output_artifacts),
                )
                write_json(
                    args.output,
                    {
                        "format_version": 1,
                        "kind": "campaign-preregistration",
                        "manifest_sha256": manifest_digest,
                        "specification_sha256": file_digest(args.specification),
                        "campaign_artifact": digest,
                        "status": campaign.status,
                        "spend_authorized": False,
                        "calibration_verified": False,
                        "primary_attempts": campaign.primary_attempts,
                        "stability_attempts": campaign.stability_attempts,
                        "worst_case_microdollars": campaign.worst_case_microdollars,
                    },
                    (args.manifest, args.specification),
                )
            elif args.command in {"validate-manifest", "validate-qualification"}:
                qualified = args.command == "validate-qualification"
                if qualified:
                    if not args.artifacts.is_dir():
                        raise ValueError("Protected artifact directory must already exist")
                    artifact_root = args.artifacts.resolve()
                    if args.output.resolve().is_relative_to(artifact_root):
                        raise ValueError("Output must remain outside protected artifact storage")
                    artifacts = ArtifactStore(artifact_root)
                    for task in tasks:
                        task.validate_qualification(artifacts)
                write_json(
                    args.output,
                    {
                        "format_version": 1,
                        "kind": (
                            "agent-qualification-validation"
                            if qualified
                            else "manifest-structural-validation"
                        ),
                        "manifest_sha256": manifest_digest,
                        "tasks": len(tasks),
                        "families": len({task.family for task in tasks}),
                        "split_counts": dict(Counter(task.split for task in tasks)),
                        "qualification_verified": qualified,
                        "qualification_mode": "independent-agents-v1" if qualified else None,
                    },
                    (args.manifest,),
                )
            elif args.command == "compare":
                trials = TypeAdapter(tuple[Trial, ...]).validate_json(args.trials.read_bytes())
                assignments = tuple(
                    ArmAssignment(
                        arm=arm,
                        split=args.split,
                        task_ids=tuple(task.id for task in tasks if task.split == args.split),
                    )
                    for arm in args.arms
                )
                comparison = compare_trials(
                    assignments, trials, seed=args.seed, bootstrap_samples=args.bootstrap_samples
                )
                write_json(
                    args.output,
                    {
                        "format_version": 1,
                        "kind": "synthetic-paired-comparison"
                        if args.synthetic
                        else "paired-comparison",
                        "manifest_sha256": manifest_digest,
                        "trials_sha256": file_digest(args.trials),
                        "qualification_verified": False,
                        "comparison": comparison,
                    },
                    (args.manifest, args.trials),
                )
            else:
                trials = TypeAdapter(tuple[Trial, ...]).validate_json(args.trials.read_bytes())
                task_splits = {task.id: task.split for task in tasks}
                seen: set[tuple[str, str, str]] = set()
                for trial in trials:
                    if task_splits.get(trial.task_id) != trial.split:
                        raise ValueError(
                            "Trial task is absent from manifest or has the wrong split"
                        )
                    identity = (trial.task_id, trial.arm, trial.split)
                    if identity in seen:
                        raise ValueError("Duplicate primary trial")
                    seen.add(identity)
                task_ids = tuple(task.id for task in tasks if task.split == args.split)
                write_json(
                    args.output,
                    {
                        "format_version": 1,
                        "kind": "synthetic-control-report" if args.synthetic else "trial-report",
                        "manifest_sha256": manifest_digest,
                        "trials_sha256": file_digest(args.trials),
                        "qualification_verified": False,
                        "report": report(task_ids, trials, args.arm, args.split),
                    },
                    (args.manifest, args.trials),
                )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
