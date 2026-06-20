from typing import List


def solve(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
