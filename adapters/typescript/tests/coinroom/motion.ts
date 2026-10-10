import * as T from "../loop_types";

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function look(player: T.Player, dx: number, dy: number): T.Player {
  return { x: player.x, z: player.z, yaw: player.yaw - dx * 0.0025,
           pitch: clamp(player.pitch - dy * 0.0025, -1.5, 1.5) };
}

export function walk(player: T.Player, keys: string[], dt: number): T.Player {
  const f = (keys.includes("w") ? 1 : 0) - (keys.includes("s") ? 1 : 0);
  const r = (keys.includes("d") ? 1 : 0) - (keys.includes("a") ? 1 : 0);
  const s = Math.sin(player.yaw), c = Math.cos(player.yaw);
  const dx = (-s * f + c * r) * 4.0 * dt;
  const dz = (-c * f - s * r) * 4.0 * dt;
  return { x: clamp(player.x + dx, -9.5, 9.5), z: clamp(player.z + dz, -9.5, 9.5),
           yaw: player.yaw, pitch: player.pitch };
}
