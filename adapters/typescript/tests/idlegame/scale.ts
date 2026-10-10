import * as T from "../loop_types";

const UNITS = ["", "K", "M", "B", "T"];

export function scale_down(value: number): T.Scaled {
  if (value < 0) throw new T.NegativeAmount(String(value));
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return { value, unit: UNITS[unit] };
}
