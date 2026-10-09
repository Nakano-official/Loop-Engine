import loop_types


def format_amount(value):
    if value < 0:
        raise loop_types.NegativeAmount(value)
    for suffix in ("", "K", "M", "B", "T"):
        if value < 1000 or suffix == "T":
            return f"{value:.2f}{suffix}"
        value /= 1000


def format_rate(value):
    return format_amount(value) + "/s"
