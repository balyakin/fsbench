"""Scoring and aggregate metric helpers."""

from math import comb, sqrt
from statistics import mean
from typing import Dict, List, Optional, Sequence, Tuple

from fsbench.errors import CheckExecutionError
from fsbench.models import CheckResult, RunResult, TaskAgentAggregate

PUBLISHED_K = [1, 2, 5, 10]


def score_run(checks: Sequence[CheckResult]) -> Tuple[bool, float]:
    """Computes pass/fail and weighted score for one run."""
    required_checks = [check for check in checks if check.required]
    passed = all(check.passed for check in required_checks)
    weight_sum = sum(check.weight for check in checks)
    if weight_sum <= 0.0:
        raise CheckExecutionError("sum of check weights must be positive")
    weighted_score = sum(check.weight * check.score for check in checks) / weight_sum
    return passed, max(0.0, min(1.0, weighted_score))


def pass_at_k(n: int, c: int, k: int) -> Optional[float]:
    """Computes pass@k using the unbiased combinatorial estimator."""
    if k > n:
        return None
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_all_at_k(n: int, c: int, k: int) -> Optional[float]:
    """Computes pass^k as the probability all sampled repeats are successful."""
    if k > n:
        return None
    if c < k:
        return 0.0
    return comb(c, k) / comb(n, k)


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """Computes a Wilson 95 percent confidence interval for a binomial proportion."""
    if total <= 0:
        raise CheckExecutionError("Wilson CI requires total > 0")
    p_hat = successes / total
    denominator = 1.0 + z * z / total
    center = (p_hat + z * z / (2.0 * total)) / denominator
    margin = z * sqrt((p_hat * (1.0 - p_hat) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def aggregate_task_agent(task_id: str, agent: str, runs: Sequence[RunResult]) -> TaskAgentAggregate:
    """Aggregates metrics for one task-agent pair."""
    if not runs:
        raise CheckExecutionError("cannot aggregate empty run list")
    sorted_runs = sorted(runs, key=lambda run: run.repeat)
    repeats = len(sorted_runs)
    successes = sum(1 for run in sorted_runs if run.passed)
    scores = [run.score for run in sorted_runs]
    costs = [run.agent_result.cost_usd for run in sorted_runs if run.agent_result.cost_usd is not None]
    durations = [run.agent_result.duration_s for run in sorted_runs]
    pass_at_1 = successes / repeats
    pass_at_k_values: Dict[str, float] = {}
    pass_all_at_k_values: Dict[str, float] = {}
    for k_value in PUBLISHED_K:
        pass_value = pass_at_k(repeats, successes, k_value)
        if pass_value is not None:
            pass_at_k_values[str(k_value)] = pass_value
        pass_all_value = pass_all_at_k(repeats, successes, k_value)
        if pass_all_value is not None:
            pass_all_at_k_values[str(k_value)] = pass_all_value
    mean_cost = mean(costs) if costs else None
    dollars_per_solve = None if mean_cost is None or pass_at_1 == 0.0 else mean_cost / pass_at_1
    return TaskAgentAggregate(
        task_id=task_id,
        agent=agent,
        repeats=repeats,
        successes=successes,
        pass_at_1=pass_at_1,
        pass_at_k=pass_at_k_values,
        pass_all_at_k=pass_all_at_k_values,
        pass_at_1_ci95=wilson_ci(successes, repeats),
        mean_score=mean(scores),
        score_std_dev=_std_dev(scores),
        mean_cost_usd=mean_cost,
        dollars_per_solve=dollars_per_solve,
        mean_duration_s=mean(durations),
    )


def aggregate_runs(runs: Sequence[RunResult]) -> List[TaskAgentAggregate]:
    """Aggregates a full run list by task and agent."""
    grouped: Dict[Tuple[str, str], List[RunResult]] = {}
    for run in runs:
        key = (run.task_id, run.agent)
        grouped.setdefault(key, []).append(run)
    aggregates: List[TaskAgentAggregate] = []
    for key, group in sorted(grouped.items()):
        task_id, agent = key
        aggregates.append(aggregate_task_agent(task_id=task_id, agent=agent, runs=group))
    return aggregates


def _std_dev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    value_mean = mean(values)
    variance = sum((value - value_mean) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance)
