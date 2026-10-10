import * as m_scale from "./scale";

export function format_amount(value: number): string {
  const s = m_scale.scale_down(value);
  return s.value.toFixed(2) + s.unit;
}

export function format_rate(value: number): string {
  return format_amount(value) + "/s";
}
