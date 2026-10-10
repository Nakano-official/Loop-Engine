import * as T from "../loop_types";

export function new_world(now: number): T.World {
  const at: [string, number, number][] = [["c1", 0, 0], ["c2", -6, -6], ["c3", 6, -6], ["c4", -6, 4], ["c5", 6, 4]];
  return { player: { x: 0.0, z: 8.0, yaw: 0.0, pitch: 0.0 },
           coins: at.map(([id, x, z]) => ({ id, x, z, taken: false })), last: now };
}
