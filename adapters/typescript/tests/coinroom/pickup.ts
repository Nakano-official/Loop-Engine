import * as T from "../loop_types";

export function collect(coins: T.Coin[], x: number, z: number): T.Coin[] {
  return coins.map((c) => ({ ...c, taken: c.taken || (c.x - x) ** 2 + (c.z - z) ** 2 <= 1.0 }));
}

export function taken_count(coins: T.Coin[]): number {
  return coins.filter((c) => c.taken).length;
}
