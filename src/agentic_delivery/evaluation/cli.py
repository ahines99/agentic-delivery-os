"""Offline manifest/schema/report tools; never runs models or benchmark candidates."""

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from agentic_delivery.config import Settings
from agentic_delivery.evaluation.campaign import (
    ArmConfiguration,
    CalibrationEvidence,
    CampaignSpecification,
    freeze_campaign,
)
from agentic_delivery.evaluation.comparison import ArmAssignment, compare_trials
from agentic_delivery.evaluation.harness import HistoricalTask, Trial, load_manifest, report
from agentic_delivery.evaluation.qualification_preparation import (
    LicenseEvidence,
    PreparationPolicy,
    PreparationRequest,
    ReferenceProvenance,
    UsageAuthorization,
    prepare_qualification,
)
from agentic_delivery.operations.export import safe_destination
from agentic_delivery.storage.artifacts import ArtifactStore


def read_preparation_document[Document: BaseModel](
    path: Path, contract: type[Document]
) -> Document:
    """Bounded local regular-file input; strict JSON ambiguity/secret-safe errors at CLI."""
    parts = path.parts[1:] if path.anchor else path.parts
    if str(path).startswith(("\\\\", "//")) or any(":" in part for part in parts):
        raise ValueError("Preparation documents must be local files")
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise ValueError("Preparation documents must not traverse links")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Preparation document must be a regular file")
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Preparation document exceeds size limit")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate preparation document key")
            result[key] = value
        return result

    def finite(value: str) -> None:
        raise ValueError("Nonfinite preparation document value")

    return contract.model_validate(json.loads(raw, object_pairs_hook=unique, parse_constant=finite))


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
    preparation = commands.add_parser(
        "prepare-qualification", help="Check protected inputs and patch binding; never execute"
    )
    for argument in (
        "config",
        "request",
        "policy",
        "artifacts",
        "output-artifacts",
        "worker-root",
        "output",
    ):
        preparation.add_argument("--" + argument, type=Path, required=True)
    schema = commands.add_parser("schema", help="Export the actual Pydantic JSON schema")
    schema.add_argument(
        "--kind",
        choices=[
            "historical-task",
            "trial",
            "campaign",
            "arm-configuration",
            "calibration",
            "preparation-request",
            "preparation-policy",
            "license-evidence",
            "usage-authorization",
            "reference-provenance",
        ],
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
                "preparation-request": PreparationRequest,
                "preparation-policy": PreparationPolicy,
                "license-evidence": LicenseEvidence,
                "usage-authorization": UsageAuthorization,
                "reference-provenance": ReferenceProvenance,
            }
            write_json(args.output, contracts[args.kind].model_json_schema())
        elif args.command == "prepare-qualification":
            settings = read_preparation_document(args.config, Settings)
            request = read_preparation_document(args.request, PreparationRequest)
            policy = read_preparation_document(args.policy, PreparationPolicy)
            for root in (args.artifacts, args.output_artifacts, args.worker_root):
                if not root.is_dir() or any(
                    part.is_symlink() or part.is_junction() for part in (root, *root.parents)
                ):
                    raise ValueError("Preparation scopes require existing unlinked directories")
            destination = safe_destination(args.output, args.config, settings)
            if destination in {args.request.resolve(), args.policy.resolve()} or any(
                destination.is_relative_to(root.resolve())
                for root in (args.artifacts, args.output_artifacts, args.worker_root)
            ):
                raise ValueError("Preparation output overlaps protected inputs or execution roots")
            prepared = prepare_qualification(
                request,
                settings=settings,
                policy=policy,
                protected_artifacts=ArtifactStore(args.artifacts),
                output_root=args.output_artifacts,
                worker_root=args.worker_root,
                now=datetime.now(UTC),
            )
            raw = (prepared.model_dump_json(indent=2) + "\n").encode()
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
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
    except (OSError, ValueError, RecursionError) as exc:
        if args.command == "prepare-qualification":
            parser.error("Qualification preparation refused; inspect protected inputs privately")
        parser.error(str(exc))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
