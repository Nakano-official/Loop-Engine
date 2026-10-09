import * as T from "../loop_types";

export function encode(state: T.GameState): string {
  return JSON.stringify({ resource: state.resource, owned: state.owned, last_update: state.last_update });
}

export function decode(text: string): T.GameState {
  let d: any;
  try { d = JSON.parse(text); } catch { throw new T.CorruptSave(text); }
  if (d === null || typeof d !== "object" || typeof d.resource !== "number"
      || typeof d.last_update !== "number" || d.owned === null || typeof d.owned !== "object") {
    throw new T.CorruptSave(text);
  }
  return { resource: d.resource, owned: { ...d.owned }, last_update: d.last_update };
}
