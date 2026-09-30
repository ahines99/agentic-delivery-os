"""One inert Markdown addition using Git objects; no checkout, hooks, filters or merge."""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from agentic_delivery.integrations.product_ops_contract.documentation import DocumentationCapability


def create_review_commit(
    capability: DocumentationCapability,
    *,
    repository: Path,
    base_branch: str,
    specification_digest: str,
    approved_at: str,
    authorize: Callable[[], None],
) -> dict[str, str]:
    """Trusted controller supplies and rechecks authority; ticket text is never argv.

    The approval timestamp fixes commit identity across retries. A single atomic ref
    transaction verifies the unchanged base and creates only a dedicated review branch.
    """
    capability = DocumentationCapability.model_validate_json(capability.model_dump_json())
    if len(specification_digest) != 64 or any(
        c not in "0123456789abcdef" for c in specification_digest
    ):
        raise ValueError("Exact specification digest required")
    executable = shutil.which("git")
    if executable is None or not repository.is_absolute():
        raise ValueError("Git and a configured absolute repository are required")
    branch = "refs/heads/delivery/doc-" + specification_digest
    base_ref = "refs/heads/" + base_branch
    with tempfile.TemporaryDirectory(prefix="delivery-documentation-") as temporary:
        directory = Path(temporary)
        hooks = directory / "hooks"
        hooks.mkdir()
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_INDEX_FILE": str(directory / "index"),
                "GIT_AUTHOR_NAME": "Agentic Delivery OS",
                "GIT_AUTHOR_EMAIL": "delivery@localhost",
                "GIT_COMMITTER_NAME": "Agentic Delivery OS",
                "GIT_COMMITTER_EMAIL": "delivery@localhost",
                "GIT_AUTHOR_DATE": approved_at,
                "GIT_COMMITTER_DATE": approved_at,
            }
        )

        def git(*args: str, data: bytes | None = None) -> bytes:
            result = subprocess.run(
                [
                    executable,
                    "--no-replace-objects",
                    "-c",
                    f"core.hooksPath={hooks}",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "gc.auto=0",
                    "-c",
                    "commit.gpgsign=false",
                    "-C",
                    str(repository),
                    *args,
                ],
                input=data,
                capture_output=True,
                env=environment,
                timeout=30,
                check=False,
            )
            if result.returncode or len(result.stdout) > 2_000_000:
                raise ValueError("Bounded documentation Git operation failed")
            return result.stdout

        authorize()
        git("check-ref-format", base_ref)
        if git("rev-parse", "--verify", base_ref).decode().strip() != capability.base_sha:
            raise ValueError("Approved repository base moved")
        if git("cat-file", "-t", capability.base_sha).strip() != b"commit":
            raise ValueError("Approved base is not a commit")
        records = git("ls-tree", "-r", "-z", capability.base_sha).split(b"\0")
        for record in filter(None, records):
            metadata, path = record.split(b"\t", 1)
            normalized = path.decode("utf-8").casefold()
            if normalized == capability.path.casefold() or normalized.startswith(
                capability.path.casefold() + "/"
            ):
                raise ValueError("Documentation addition would overwrite an existing path")
            if normalized == "docs" or (
                normalized.startswith("docs/") and not path.startswith(b"docs/")
            ):
                raise ValueError("Documentation parent is a link, file or case collision")
            if metadata.startswith((b"120000", b"160000")) and normalized == "docs":
                raise ValueError("Documentation parent is not a plain tree")
        git("read-tree", capability.base_sha)
        blob = (
            git("hash-object", "-w", "--stdin", data=capability.content.encode()).decode().strip()
        )
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{capability.path}")
        tree = git("write-tree").decode().strip()
        if git(
            "diff-tree", "--no-commit-id", "--name-status", "-r", "-z", capability.base_sha, tree
        ) != (b"A\0" + capability.path.encode() + b"\0"):
            raise ValueError("Documentation change set is not exactly one addition")
        if git("cat-file", "blob", blob) != capability.content.encode():
            raise ValueError("Documentation blob differs from approved bytes")
        message = (
            f"Add approved documentation\n\nProduct Ops specification: {specification_digest}\n"
        )
        commit = (
            git("commit-tree", tree, "-p", capability.base_sha, data=message.encode())
            .decode()
            .strip()
        )
        authorize()
        existing = git("for-each-ref", "--format=%(objectname)", branch).decode().strip()
        if existing and existing != commit:
            raise ValueError("Review branch already contains a different change")
        commands = f"start\nverify {base_ref} {capability.base_sha}\n"
        commands += f"verify {branch} {commit}\n" if existing else f"create {branch} {commit}\n"
        git("update-ref", "--stdin", data=(commands + "prepare\ncommit\n").encode())
        return {
            "state": "HUMAN_REVIEW",
            "repository": capability.repository_id,
            "base_sha": capability.base_sha,
            "head_sha": commit,
            "branch": branch,
            "path": capability.path,
            "blob_sha": blob,
            "policy_version": capability.policy_version,
            "approved_specification_digest": specification_digest,
            "publication": "local_review_branch",
            "merge": "requires_human",
        }
