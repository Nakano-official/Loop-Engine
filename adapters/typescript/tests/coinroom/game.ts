import * as T from "../loop_types";
import * as m_layout from "./layout";
import * as m_motion from "./motion";
import * as m_pickup from "./pickup";
import * as m_save from "./save";
import * as m_scene from "./scene";

export function start(now: number, saved: string | null): T.World {
  if (saved === null) return m_layout.new_world(now);
  return { ...m_save.decode(saved), last: now };
}

export function step(state: T.World, now: number, input: T.Input): T.World {
  const dt = Math.min(Math.max(now - state.last, 0.0), 0.25);
  let p = state.player;
  if (input.locked) p = m_motion.look(p, input.mouse_dx, input.mouse_dy);
  p = m_motion.walk(p, input.keys, dt);
  return { player: p, coins: m_pickup.collect(state.coins, p.x, p.z), last: now };
}

export function act(state: T.World, action: string, now: number): T.World {
  return action === "restart" ? m_layout.new_world(now) : state;
}

export function screen(state: T.World): T.Scene { return m_scene.build(state); }
export function save(state: T.World): string { return m_save.encode(state); }
