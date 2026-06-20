VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def solve(value: str) -> int:
    total = 0
    previous = 0
    for ch in reversed(value):
        current = VALUES[ch]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total
