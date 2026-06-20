from fsbench.models import CheckResult, CheckType
from fsbench.scoring import pass_all_at_k, pass_at_k, score_run, wilson_ci


def test_score_run_weighted_score() -> None:
    # ARRANGE
    checks = [
        CheckResult(name="a", type=CheckType.FILE_EXISTS, required=True, weight=1.0, passed=True, score=1.0),
        CheckResult(name="b", type=CheckType.FILE_EXISTS, required=False, weight=3.0, passed=False, score=0.0),
    ]

    # ACT
    passed, score = score_run(checks)

    # ASSERT
    assert passed is True
    assert score == 0.25


def test_pass_at_k_formula() -> None:
    # ARRANGE
    n = 5
    c = 2

    # ACT
    value = pass_at_k(n, c, 2)

    # ASSERT
    assert value == 0.7


def test_pass_all_at_k_formula() -> None:
    # ARRANGE
    n = 5
    c = 2

    # ACT
    value = pass_all_at_k(n, c, 2)

    # ASSERT
    assert value == 0.1


def test_wilson_contains_observed_proportion() -> None:
    # ARRANGE
    successes = 3
    total = 5

    # ACT
    low, high = wilson_ci(successes, total)

    # ASSERT
    assert low <= successes / total <= high
