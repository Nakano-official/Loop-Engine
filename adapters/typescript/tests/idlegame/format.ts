import * as T from "../loop_types";

export function format_amount(value: number): string {
  if (value < 0) throw new T.NegativeAmount(String(value));
  for (const suffix of ["", "K", "M", "B", "T"]) {
    if (value < 1000 || suffix === "T") return value.toFixed(2) + suffix;
    value /= 1000;
  }
  throw new Error("unreachable");
}

export function format_rate(value: number): string {
  return format_amount(value) + "/s";
}
