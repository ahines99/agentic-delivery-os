"""Exercise the packaged Product Ops contract outside the checkout with locked deps."""

import os
import subprocess
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    wheels = list((ROOT / "dist").glob("agentic_delivery_os-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Build exactly one Delivery wheel before this smoke check")
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory(prefix="delivery-contract-wheel-") as directory:
        scratch = Path(directory).resolve()
        target = scratch / "venv"
        venv.create(target, with_pip=False)
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirements = scratch / "runtime.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--quiet",
                "--output-file",
                str(requirements),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "-r",
                str(requirements),
            ],
            cwd=scratch,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(wheels[0]),
            ],
            cwd=scratch,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from pathlib import Path; from importlib.resources import files; "
                "import agentic_delivery as p; "
                "from agentic_delivery.integrations.product_ops import admit; "
                "from agentic_delivery.integrations.product_ops_documentation "
                "import execute_documentation; "
                "from agentic_delivery.integrations.product_ops_contract.linear_markdown "
                "import descriptions_match; "
                f"assert Path(p.__file__).is_relative_to({str(target)!r}); "
                "assert files('agentic_delivery.integrations.product_ops_contract')"
                ".joinpath('handoff-v2.schema.json').is_file(); "
                "assert descriptions_match('## Title\\nText', '## Title\\n\\nText'); "
                "assert not descriptions_match('keep approval', 'skip approval')",
            ],
            cwd=scratch,
            env=env,
            check=True,
        )
    print("Clean wheel: signed handoff, packaged schema, executor and Markdown guard import/pass")


if __name__ == "__main__":
    main()
