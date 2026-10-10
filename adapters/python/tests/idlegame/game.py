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


def start(now, saved):
    return load(saved, now)


def step(state, now):
    return tick(state, now)


def act(state, action, now):
    if action == "click":
        return click(state)
    if action.startswith("buy:"):
        return buy(state, action[4:])
    return state


def screen(state):
    v = view(state)

    def node(kind, text, action="", enabled=True):
        return loop_types.Node(kind=loop_types.NodeKind(kind), text=text, action=action, enabled=enabled)

    nodes = [node("heading", "放置ゲーム"), node("text", "資源 " + v.resource_text),
             node("text", "生産 " + v.rate_text), node("button", "Click", "click")]
    for row in v.rows:
        nodes += [node("text", row.label), node("button", row.button_label, "buy:" + row.name, row.affordable)]
    return loop_types.Screen(title="放置ゲーム", nodes=nodes)
