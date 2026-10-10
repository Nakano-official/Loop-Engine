import * as T from "../loop_types";
import * as m_pickup from "./pickup";

const v = (x: number, y: number, z: number): T.Vec3 => ({ x, y, z });
const WALL = "#c9b79c";

export function build(world: T.World): T.Scene {
  const p = world.player;
  const n = m_pickup.taken_count(world.coins), total = world.coins.length;
  const objects: T.Object3D[] = [
    { id: "floor", shape: "plane", position: v(0, 0, 0), size: v(20, 0, 20), rotation_y: 0, color: "#6b8f5e" },
    { id: "wall-n", shape: "box", position: v(0, 1.5, -10), size: v(20, 3, 0.2), rotation_y: 0, color: WALL },
    { id: "wall-s", shape: "box", position: v(0, 1.5, 10), size: v(20, 3, 0.2), rotation_y: 0, color: WALL },
    { id: "wall-e", shape: "box", position: v(10, 1.5, 0), size: v(0.2, 3, 20), rotation_y: 0, color: WALL },
    { id: "wall-w", shape: "box", position: v(-10, 1.5, 0), size: v(0.2, 3, 20), rotation_y: 0, color: WALL },
  ];
  for (const c of world.coins) {
    if (!c.taken) objects.push({ id: "coin-" + c.id, shape: "sphere", position: v(c.x, 0.5, c.z),
                                 size: v(0.5, 0.5, 0.5), rotation_y: 0, color: "#f2c14e" });
  }
  const text = (t: string): T.Node => ({ kind: "text", text: t, action: "", enabled: true });
  const hud: T.Node[] = [{ kind: "heading", text: "コイン集め", action: "", enabled: true },
                         text(`コイン ${n} / ${total}`)];
  if (n === total) {
    hud.push(text("ぜんぶ集めた！"), { kind: "button", text: "もう一度", action: "restart", enabled: true });
  } else {
    hud.push(text("WASD で歩く・クリックで見回す"));
  }
  return { title: "コイン集め", camera: { position: v(p.x, 1.6, p.z), yaw: p.yaw, pitch: p.pitch, fov: 70.0 },
           objects, hud };
}
