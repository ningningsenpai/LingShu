def clamp(value: int, lower: int, upper: int) -> int:
    if lower > upper:
        raise ValueError("下界不能大于上界")
    return min(lower, max(value, upper))
