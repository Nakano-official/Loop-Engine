import * as T from "../loop_types";

export function current_cost(spec: T.GeneratorSpec, owned: number): number {
  return spec.base_cost * spec.cost_scale ** owned;
}

export function production_rate(owned: Readonly<Record<string, number>>,
                                catalog: ReadonlyArray<T.GeneratorSpec>): number {
  let total = 0;
  for (const [name, count] of Object.entries(owned)) {
    const spec = catalog.find((s) => s.name === name);
    if (spec === undefined) throw new T.UnknownGenerator(name);
    total += count * spec.base_rate;
  }
  return total;
}
