from typing import Dict, List, Set


def solve(graph: Dict[str, List[str]]) -> List[str]:
    result: List[str] = []
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError("cycle detected")
        visiting.add(node)
        for dependency in sorted(graph.get(node, [])):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
        result.append(node)

    for node in sorted(graph):
        visit(node)
    return result
