import * as T from "../loop_types";

export function encode(world: T.World): string {
  return JSON.stringify({ player: world.player, coins: world.coins, last: world.last });
}

const num = (v: unknown) => typeof v === "number";

export function decode(text: string): T.World {
  let d: any;
  try { d = JSON.parse(text); } catch { throw new T.CorruptSave(text); }
  const p = d?.player;
  if (d === null || typeof d !== "object" || p === null || typeof p !== "object"
      || !num(p.x) || !num(p.z) || !num(p.yaw) || !num(p.pitch) || !Array.isArray(d.coins) || !num(d.last)
      || !d.coins.every((c: any) => c !== null && typeof c === "object" && typeof c.id === "string"
                                   && num(c.x) && num(c.z) && typeof c.taken === "boolean")) {
    throw new T.CorruptSave(text);
  }
  return { player: { x: p.x, z: p.z, yaw: p.yaw, pitch: p.pitch },
           coins: d.coins.map((c: any) => ({ id: c.id, x: c.x, z: c.z, taken: c.taken })), last: d.last };
}
