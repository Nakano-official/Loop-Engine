import loop_types
from app import economy as m_economy
from app import format as m_format


def render(state, catalog):
    rows = []
    for spec in catalog:
        n = state.owned.get(spec.name, 0)
        cost = m_economy.current_cost(spec, n)
        rows.append(loop_types.Row(name=spec.name, label=f"{spec.name} x{n}",
                                   button_label=f"Buy {spec.name} ({m_format.format_amount(cost)})",
                                   affordable=state.resource >= cost))
    return loop_types.View(resource_text=m_format.format_amount(state.resource),
                           rate_text=m_format.format_rate(m_economy.production_rate(state.owned, catalog)),
                           rows=rows)
