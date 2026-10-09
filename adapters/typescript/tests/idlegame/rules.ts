import * as T from "../loop_types";
import * as m_catalog from "./catalog";
import * as m_economy from "./economy";

export function click(state: T.GameState): T.GameState {
  return { ...state, resource: state.resource + 1.0 };
}

export function buy(state: T.GameState, catalog: ReadonlyArray<T.GeneratorSpec>, name: string): T.GameState {
  const spec = m_catalog.find_spec(catalog, name);
  const owned = state.owned[name] ?? 0;
  const cost = m_economy.current_cost(spec, owned);
  if (state.resource < cost) throw new T.NotEnough(name);
  return { ...state, resource: state.resource - cost, owned: { ...state.owned, [name]: owned + 1 } };
}

export function tick(state: T.GameState, catalog: ReadonlyArray<T.GeneratorSpec>, now: number): T.GameState {
  const dt = now - state.last_update;
  if (dt < 0) throw new T.TimeWentBackwards(String(now));
  const rate = m_economy.production_rate(state.owned, catalog);
  return { ...state, resource: state.resource + rate * dt, last_update: now };
}
