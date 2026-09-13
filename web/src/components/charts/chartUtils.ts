import type { AnalyticsDay } from "../../types";

export const chartColors = {
  blue: "#315bf5",
  blueSoft: "rgba(49, 91, 245, 0.14)",
  cached: "#9bb5ff",
  green: "#18a875",
  warning: "#b8740b",
  ink: "#17223b",
  muted: "#68758c",
  line: "#e4eaf4",
};

export function compactNumber(value: number): string {
  if (value >= 100_000_000) return `${trimDecimal(value / 100_000_000)}亿`;
  if (value >= 10_000) return `${trimDecimal(value / 10_000)}万`;
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function dayLabel(days: AnalyticsDay[], index: number): string {
  const relativeLabels = ["前天", "昨天", "今天"];
  const date = days[index]?.date ?? "";
  if (days.length === 3) {
    return `${relativeLabels[index] ?? date}\n${date.slice(5)}`;
  }

  const [, month, day] = date.split("-");
  return month && day ? `${Number(month)}/${Number(day)}` : date;
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character] ?? character);
}

export function tooltipIndex(parameters: unknown): number {
  const first = Array.isArray(parameters) ? parameters[0] : parameters;
  if (!first || typeof first !== "object" || !("dataIndex" in first)) return 0;
  const value = (first as { dataIndex?: unknown }).dataIndex;
  return typeof value === "number" ? value : 0;
}

export function knownTokenTotal(day: AnalyticsDay): number {
  return day.non_cached_input_tokens + day.cached_input_tokens + day.output_tokens;
}

function trimDecimal(value: number): string {
  return value >= 10 ? value.toFixed(0) : value.toFixed(1).replace(/\.0$/, "");
}
