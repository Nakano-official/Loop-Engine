import * as T from "../loop_types";
import * as m_catalog from "./catalog";
import * as m_rules from "./rules";
import * as m_save from "./save";
import * as m_view from "./view";

export function new_game(now: number): T.GameState {
  return { resource: 0.0, owned: {}, last_update: now };
}
export function click(state: T.GameState): T.GameState { return m_rules.click(state); }
export function buy(state: T.GameState, name: string): T.GameState {
  return m_rules.buy(state, m_catalog.default_catalog(), name);
}
export function tick(state: T.GameState, now: number): T.GameState {
  return m_rules.tick(state, m_catalog.default_catalog(), now);
}
export function view(state: T.GameState): T.View { return m_view.render(state, m_catalog.default_catalog()); }
export function save(state: T.GameState): string { return m_save.encode(state); }
export function load(saved: string | null, now: number): T.GameState {
  if (saved === null) return new_game(now);
  return m_rules.tick(m_save.decode(saved), m_catalog.default_catalog(), now);
}
