from collections import OrderedDict
from typing import List, Optional, Tuple


def solve(operations: List[Tuple[str, int, Optional[int]]], capacity: int) -> List[int]:
    cache: OrderedDict[int, int] = OrderedDict()
    output: List[int] = []
    for op, key, value in operations:
        if op == "get":
            if key not in cache:
                output.append(-1)
            else:
                cache.move_to_end(key)
                output.append(cache[key])
        elif op == "put" and value is not None and capacity > 0:
            if key in cache:
                cache.move_to_end(key)
            cache[key] = value
            if len(cache) > capacity:
                cache.popitem(last=False)
    return output
