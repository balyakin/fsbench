from typing import Dict, List


def solve(items: List[Dict[str, float]]) -> float:
    total = 0.0
    for item in items:
        total += item["price"] * item.get("quantity", 1)
    return round(total, 2)
