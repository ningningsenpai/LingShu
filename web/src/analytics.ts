import type { AnalyticsMetrics } from "./types";

export type AnalyticsMode = "calls" | "tokens";
export type TimeRange = "7" | "30" | "90" | "custom";

export const TIME_RANGE_OPTIONS: Array<{ value: TimeRange; label: string }> = [
  { value: "7", label: "近 7 天" },
  { value: "30", label: "近 30 天" },
  { value: "90", label: "近 90 天" },
  { value: "custom", label: "自定义" },
];

export const emptyAnalyticsMetrics = (): AnalyticsMetrics => ({
  attempts: 0,
  responded: 0,
  succeeded: 0,
  attempting: 0,
  outcome_unknown: 0,
  usage_known_calls: 0,
  usage_unknown_calls: 0,
  input_tokens: 0,
  cached_input_tokens: 0,
  non_cached_input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  subscription_attempts: 0,
});

export function sumAnalyticsMetrics(items: AnalyticsMetrics[]): AnalyticsMetrics {
  return items.reduce((total, item) => {
    for (const key of Object.keys(total) as Array<keyof AnalyticsMetrics>) {
      total[key] += item[key];
    }
    return total;
  }, emptyAnalyticsMetrics());
}

export function chartMaximum(items: AnalyticsMetrics[], mode: AnalyticsMode): number {
  const values = items.map((item) => mode === "calls" ? item.attempts : item.total_tokens);
  return Math.max(1, ...values);
}

export function barHeight(value: number, maximum: number): number {
  if (value <= 0) return 0;
  return Math.max(4, Math.min(100, (value / Math.max(1, maximum)) * 100));
}

export function tokenParts(metrics: AnalyticsMetrics): Array<{
  key: "non-cached" | "cached" | "output";
  label: string;
  value: number;
}> {
  return [
    { key: "non-cached", label: "非缓存输入", value: metrics.non_cached_input_tokens },
    { key: "cached", label: "缓存输入", value: metrics.cached_input_tokens },
    { key: "output", label: "输出", value: metrics.output_tokens },
  ];
}

export function shanghaiDate(daysAgo = 0): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const timestamp = Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day) - daysAgo,
  );
  return new Date(timestamp).toISOString().slice(0, 10);
}

export function buildAnalyticsParameters(options: {
  range: TimeRange;
  startDate: string;
  endDate: string;
  provider?: string;
  model?: string;
}): URLSearchParams {
  const parameters = new URLSearchParams();
  if (options.range === "custom") {
    parameters.set("start_date", options.startDate);
    parameters.set("end_date", options.endDate);
  } else {
    parameters.set("days", options.range);
  }
  if (options.provider) parameters.set("provider", options.provider);
  if (options.model) parameters.set("model", options.model);
  return parameters;
}
