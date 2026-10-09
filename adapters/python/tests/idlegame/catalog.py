import loop_types

_CATALOG = [
    ("cursor", 15.0, 0.25, 1.5),
    ("grandma", 100.0, 2.0, 1.5),
]


def default_catalog():
    return [loop_types.GeneratorSpec(name=n, base_cost=c, base_rate=r, cost_scale=s)
            for n, c, r, s in _CATALOG]


def find_spec(catalog, name):
    for spec in catalog:
        if spec.name == name:
            return spec
    raise loop_types.UnknownGenerator(name)
