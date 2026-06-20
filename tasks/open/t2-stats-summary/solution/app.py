from typing import Dict, List


def solve(values: List[int]) -> Dict[str, float]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0.0}
    return {"min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 2)}
