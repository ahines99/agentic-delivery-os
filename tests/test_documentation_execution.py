import subprocess

import pytest

from agentic_delivery.execution.documentation import create_review_commit
from agentic_delivery.integrations.product_ops_contract.documentation import DocumentationCapability


def git(root, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@localhost")
    (root / "README.md").write_text("Test repository\n")
    git(root, "add", "README.md")
    git(root, "-c", "core.hooksPath=" + str(tmp_path / "empty"), "commit", "-m", "Base")
    return root


def capability(root):
    return DocumentationCapability(
        semantic_digest="a" * 64,
        repository_id="test",
        base_sha=git(root, "rev-parse", "HEAD").decode(),
        path="docs/success.md",
        content="# Success\n\nExact approved content.\n",
    )


def execute(root, cap, check=lambda: None):
    return create_review_commit(
        cap,
        repository=root,
        base_branch="main",
        specification_digest="b" * 64,
        approved_at="2026-09-29T12:00:00+00:00",
        authorize=check,
    )


def test_exact_addition_is_repeatable_and_never_changes_worktree_or_main(repository, tmp_path):
    cap = capability(repository)
    # A hostile hook must not run; no shell command from the repository is invoked.
    marker = tmp_path / "hook-ran"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(f'#!/bin/sh\necho bad > "{marker.as_posix()}"\n')
    hook.chmod(0o755)
    git(repository, "config", "core.hooksPath", str(hooks))
    calls = []
    first = execute(repository, cap, lambda: calls.append("checked"))
    assert calls == ["checked", "checked"]
    assert execute(repository, cap) == first
    assert git(repository, "rev-parse", "main").decode() == cap.base_sha
    assert git(repository, "status", "--porcelain") == b""
    assert not marker.exists()
    assert not (repository / cap.path).exists()
    assert (
        git(repository, "diff", "--name-status", cap.base_sha, first["head_sha"])
        == b"A\tdocs/success.md"
    )
    assert (
        git(repository, "show", first["head_sha"] + ":" + cap.path) + b"\n" == cap.content.encode()
    )


@pytest.mark.parametrize("fault", ["base", "overwrite", "parent", "revocation"])
def test_denials_never_create_review_branch(repository, fault):
    cap = capability(repository)
    if fault in {"overwrite", "parent", "base"}:
        path = repository / (
            cap.path if fault == "overwrite" else "docs" if fault == "parent" else "new.txt"
        )
        path.parent.mkdir(exist_ok=True)
        path.write_text("existing\n")
        git(repository, "add", ".")
        git(repository, "commit", "-m", "Another change")
        if fault != "base":
            cap = cap.model_copy(update={"base_sha": git(repository, "rev-parse", "HEAD").decode()})
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if fault == "revocation" and calls == 2:
            raise ValueError("revoked")

    with pytest.raises(ValueError):
        execute(repository, cap, check)
    assert git(repository, "for-each-ref", "--format=%(refname)", "refs/heads/delivery/") == b""
