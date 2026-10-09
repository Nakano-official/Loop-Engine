import * as T from "../loop_types";
import * as m_economy from "./economy";
import * as m_format from "./format";

export function render(state: T.GameState, catalog: ReadonlyArray<T.GeneratorSpec>): T.View {
  const rows = catalog.map((spec) => {
    const n = state.owned[spec.name] ?? 0;
    const cost = m_economy.current_cost(spec, n);
    return { name: spec.name, label: `${spec.name} x${n}`,
             button_label: `Buy ${spec.name} (${m_format.format_amount(cost)})`,
             affordable: state.resource >= cost };
  });
  return { resource_text: m_format.format_amount(state.resource),
           rate_text: m_format.format_rate(m_economy.production_rate(state.owned, catalog)),
           rows };
}
