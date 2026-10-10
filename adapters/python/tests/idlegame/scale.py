import loop_types

_UNITS = ["", "K", "M", "B", "T"]


def scale_down(value):
    if value < 0:
        raise loop_types.NegativeAmount(value)
    unit = 0
    while value >= 1000 and unit < len(_UNITS) - 1:
        value /= 1000
        unit += 1
    return loop_types.Scaled(value=value, unit=_UNITS[unit])
