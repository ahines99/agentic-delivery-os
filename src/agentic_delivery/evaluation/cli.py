"""Offline manifest/schema/report tools; never runs models or benchmark candidates."""

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from agentic_delivery.evaluation.harness import HistoricalTask, Trial, load_manifest, report


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
    schema = commands.add_parser("schema", help="Export the actual Pydantic JSON schema")
    schema.add_argument("--kind", choices=["historical-task", "trial"], required=True)
    schema.add_argument("--output", type=Path, required=True)
    summarize = commands.add_parser("report", help="Report recorded trials; does not run tasks")
    summarize.add_argument("--manifest", type=Path, required=True)
    summarize.add_argument("--trials", type=Path, required=True, help="JSON array of Trial records")
    summarize.add_argument("--arm", choices=["A", "B", "C"], required=True)
    summarize.add_argument("--split", choices=["development", "validation", "test"], required=True)
    summarize.add_argument("--synthetic", action="store_true", help="Label synthetic control data")
    summarize.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            contract = HistoricalTask if args.kind == "historical-task" else Trial
            write_json(args.output, contract.model_json_schema())
        else:
            tasks = load_manifest(args.manifest)
            manifest_digest = file_digest(args.manifest)
            if args.command == "validate-manifest":
                write_json(
                    args.output,
                    {
                        "format_version": 1,
                        "kind": "manifest-structural-validation",
                        "manifest_sha256": manifest_digest,
                        "tasks": len(tasks),
                        "families": len({task.family for task in tasks}),
                        "split_counts": dict(Counter(task.split for task in tasks)),
                        "qualification_verified": False,
                    },
                    (args.manifest,),
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
