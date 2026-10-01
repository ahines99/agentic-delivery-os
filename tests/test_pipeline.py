"""Control tests inject model/runner results; live smoke scripts exercise actual providers."""

from pathlib import Path

import pytest

from agentic_delivery.agents.contracts import BuildProposal, CriterionTests, FileEdit
from agentic_delivery.agents.pipeline import build_and_review
from agentic_delivery.domain.models import VerificationType, WorkItem
from agentic_delivery.execution.files import apply_edits


def test_existing_tests_are_protected_even_if_builder_requests_removal() -> None:
    import hashlib

    original = "def test_behavior(): assert True\n"
    proposal = BuildProposal(
        summary="Malicious weakening",
        edits=(
            FileEdit(
                path="tests/test_base.py",
                original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                content=None,
            ),
        ),
        criterion_tests=(CriterionTests(criterion_id="AC-1", tests=("tests/test_base.py",)),),
    )
    with pytest.raises(ValueError, match="protected"):
        apply_edits({"tests/test_base.py": original}, proposal.edits, ("tests/test_base.py",))


@pytest.mark.parametrize(
    "path",
    ["pytest.py", "pytest/__init__.py", "tests/conftest.py", "pyproject.toml", "requirements.txt"],
)
def test_builder_cannot_replace_test_runtime_or_dependency_controls(path: str) -> None:
    with pytest.raises(ValueError, match="protected"):
        apply_edits({}, (FileEdit(path=path, original_sha256=None, content="fake tests"),), ())


@pytest.mark.parametrize(
    "kind",
    [VerificationType.MANUAL_REVIEW, VerificationType.BENCHMARK, VerificationType.STATIC_ANALYSIS],
)
async def test_unsupported_evidence_cannot_be_replaced_with_pytest(kind: VerificationType) -> None:
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(
        update={
            "acceptance_criteria": (
                item.acceptance_criteria[0].model_copy(update={"verification_type": kind}),
            )
        }
    )
    # Reject before constructing any provider, runner, or other effectful dependency.
    with pytest.raises(ValueError, match="cannot satisfy"):
        await build_and_review("id", item, None, {}, "a" * 40, None, None, None)
