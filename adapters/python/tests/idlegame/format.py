from app import scale as m_scale


def format_amount(value):
    s = m_scale.scale_down(value)
    return f"{s.value:.2f}{s.unit}"


def format_rate(value):
    return format_amount(value) + "/s"
