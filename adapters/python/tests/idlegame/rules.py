import dataclasses

import loop_types
from app import catalog as m_catalog
from app import economy as m_economy


def click(state):
    return dataclasses.replace(state, resource=state.resource + 1.0)


def buy(state, catalog, name):
    spec = m_catalog.find_spec(catalog, name)
    owned = state.owned.get(name, 0)
    cost = m_economy.current_cost(spec, owned)
    if state.resource < cost:
        raise loop_types.NotEnough(name)
    return dataclasses.replace(state, resource=state.resource - cost,
                               owned={**state.owned, name: owned + 1})


def tick(state, catalog, now):
    dt = now - state.last_update
    if dt < 0:
        raise loop_types.TimeWentBackwards(now)
    rate = m_economy.production_rate(state.owned, catalog)
    return dataclasses.replace(state, resource=state.resource + rate * dt, last_update=now)
