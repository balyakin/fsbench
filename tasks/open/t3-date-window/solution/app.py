from datetime import date, timedelta
from typing import List


def solve(start: str, days: int) -> List[str]:
    if days <= 0:
        return []
    current = date.fromisoformat(start)
    return [(current + timedelta(days=offset)).isoformat() for offset in range(days)]
