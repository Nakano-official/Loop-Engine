import json

import loop_types


def encode(state):
    return json.dumps({"resource": state.resource, "owned": state.owned,
                       "last_update": state.last_update})


def decode(text):
    try:
        d = json.loads(text)
        return loop_types.GameState(resource=float(d["resource"]),
                                    owned={k: int(v) for k, v in d["owned"].items()},
                                    last_update=float(d["last_update"]))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise loop_types.CorruptSave(text) from None
