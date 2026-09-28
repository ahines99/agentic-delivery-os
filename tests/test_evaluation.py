import pytest

from agentic_delivery.evaluation.harness import Trial, report, wilson
from agentic_delivery.policy.changes import check_candidate


def trial(task: str, status: str, ready: bool = False) -> Trial:
    return Trial(
        task_id=task,
        arm="A",
        split="test",
        status=status,
        declared_ready=ready,
        regression_failed=False,
        regression_completed=True,
        model_microdollars=1000,
        infrastructure_microdollars=100,
        active_seconds=1,
        human_minutes=0,
    )


def test_missing_and_failed_tasks_remain_in_denominator() -> None:
    result = report(
        ("one", "two", "three"), (trial("one", "PASS"), trial("two", "TIMEOUT", True)), "A", "test"
    )
    assert result["strict_success_rate"] == 1 / 3
    assert result["missing_task_ids"] == ["three"]
    assert result["false_ready_numerator"] == 1
    assert result["total_microdollars"] == 2200
    assert result["microdollars_per_success"] == 2200


def test_zero_denominator_is_not_success_and_duplicates_rejected() -> None:
    assert wilson(0, 0) is None
    assert report((), (), "A", "test")["strict_success_rate"] is None
    with pytest.raises(ValueError):
        report(("one",), (trial("one", "PASS"), trial("one", "FAIL")), "A", "test")


@pytest.mark.parametrize(
    "path,code",
    [
        ("auth.py", "pass"),
        ("app.py", "def authorize_user(): return True"),
        ("app.py", "exec(input())"),
        ("app.py", "token = '" + "sk-" + "x" * 30 + "'"),
    ],
)
def test_new_sensitive_behavior_and_credentials_escalate(path: str, code: str) -> None:
    with pytest.raises(ValueError):
        check_candidate({}, {path: code})
