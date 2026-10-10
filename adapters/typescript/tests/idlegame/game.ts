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

export function start(now: number, saved: string | null): T.GameState { return load(saved, now); }
export function step(state: T.GameState, now: number): T.GameState { return tick(state, now); }
export function act(state: T.GameState, action: string, _now: number): T.GameState {
  if (action === "click") return click(state);
  if (action.startsWith("buy:")) return buy(state, action.slice(4));
  return state;
}
export function screen(state: T.GameState): T.Screen {
  const v = view(state);
  const nodes: T.Node[] = [
    { kind: "heading", text: "放置ゲーム", action: "", enabled: true },
    { kind: "text", text: "資源 " + v.resource_text, action: "", enabled: true },
    { kind: "text", text: "生産 " + v.rate_text, action: "", enabled: true },
    { kind: "button", text: "Click", action: "click", enabled: true },
  ];
  for (const row of v.rows) {
    nodes.push({ kind: "text", text: row.label, action: "", enabled: true });
    nodes.push({ kind: "button", text: row.button_label, action: "buy:" + row.name, enabled: row.affordable });
  }
  return { title: "放置ゲーム", nodes };
}
