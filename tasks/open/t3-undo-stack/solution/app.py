from typing import List, Tuple


def solve(operations: List[Tuple[str, str]]) -> str:
    value = ""
    undo_stack: List[str] = []
    redo_stack: List[str] = []
    for op, arg in operations:
        if op == "append":
            undo_stack.append(value)
            redo_stack.clear()
            value += arg
        elif op == "undo" and undo_stack:
            redo_stack.append(value)
            value = undo_stack.pop()
        elif op == "redo" and redo_stack:
            undo_stack.append(value)
            value = redo_stack.pop()
    return value
