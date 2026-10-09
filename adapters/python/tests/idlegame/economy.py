import loop_types


def current_cost(spec, owned):
    return spec.base_cost * spec.cost_scale ** owned


def production_rate(owned, catalog):
    rates = {spec.name: spec.base_rate for spec in catalog}
    total = 0.0
    for name, count in owned.items():
        if name not in rates:
            raise loop_types.UnknownGenerator(name)
        total += count * rates[name]
    return total
