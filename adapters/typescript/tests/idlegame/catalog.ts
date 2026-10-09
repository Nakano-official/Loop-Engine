import * as T from "../loop_types";

export function default_catalog(): T.GeneratorSpec[] {
  return [
    { name: "cursor", base_cost: 15.0, base_rate: 0.25, cost_scale: 1.5 },
    { name: "grandma", base_cost: 100.0, base_rate: 2.0, cost_scale: 1.5 },
  ];
}

export function find_spec(catalog: ReadonlyArray<T.GeneratorSpec>, name: string): T.GeneratorSpec {
  const spec = catalog.find((s) => s.name === name);
  if (spec === undefined) throw new T.UnknownGenerator(name);
  return spec;
}
