from typing import Dict
from urllib.parse import unquote_plus


def solve(query: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if query.startswith("?"):
        query = query[1:]
    for part in query.split("&"):
        if not part:
            continue
        key, separator, value = part.partition("=")
        result[unquote_plus(key)] = unquote_plus(value if separator else "")
    return result
