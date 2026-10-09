import loop_types
from app import catalog as m_catalog
from app import rules as m_rules
from app import save as m_save
from app import view as m_view


def new_game(now):
    return loop_types.GameState(resource=0.0, owned={}, last_update=now)


def click(state):
    return m_rules.click(state)


def buy(state, name):
    return m_rules.buy(state, m_catalog.default_catalog(), name)


def tick(state, now):
    return m_rules.tick(state, m_catalog.default_catalog(), now)


def view(state):
    return m_view.render(state, m_catalog.default_catalog())


def save(state):
    return m_save.encode(state)


def load(saved, now):
    if saved is None:
        return new_game(now)
    return m_rules.tick(m_save.decode(saved), m_catalog.default_catalog(), now)
