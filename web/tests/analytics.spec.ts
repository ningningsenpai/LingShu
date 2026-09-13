import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import {
  barHeight,
  chartMaximum,
  emptyAnalyticsMetrics,
  sumAnalyticsMetrics,
  tokenParts,
} from "../src/analytics";
import DailyMetricChart from "../src/components/DailyMetricChart.vue";
import type { AnalyticsMetrics } from "../src/types";

function metrics(overrides: Partial<AnalyticsMetrics>): AnalyticsMetrics {
  return { ...emptyAnalyticsMetrics(), ...overrides };
}

describe("三日分析图表", () => {
  it("分别使用调用次数与 Token 总量确定图表比例", () => {
    const values = [
      metrics({ attempts: 3, total_tokens: 120 }),
      metrics({ attempts: 7, total_tokens: 80 }),
    ];

    expect(chartMaximum(values, "calls")).toBe(7);
    expect(chartMaximum(values, "tokens")).toBe(120);
    expect(barHeight(60, 120)).toBe(50);
    expect(barHeight(0, 120)).toBe(0);
  });

  it("Token 堆叠只使用非缓存输入、缓存输入与输出", () => {
    const value = metrics({
      input_tokens: 100,
      non_cached_input_tokens: 60,
      cached_input_tokens: 40,
      output_tokens: 20,
      total_tokens: 120,
    });

    const parts = tokenParts(value);
    expect(parts.map((part) => part.value)).toEqual([60, 40, 20]);
    expect(parts.reduce((sum, part) => sum + part.value, 0)).toBe(value.total_tokens);
  });

  it("汇总 Provider 指标时保持所有字段独立累加", () => {
    const total = sumAnalyticsMetrics([
      metrics({ attempts: 2, responded: 1, total_tokens: 100 }),
      metrics({ attempts: 3, responded: 2, total_tokens: 240 }),
    ]);

    expect(total.attempts).toBe(5);
    expect(total.responded).toBe(3);
    expect(total.total_tokens).toBe(340);
  });

  it("为三日 Token 柱提供键盘焦点与可读数据说明", () => {
    const days = [
      { date: "2026-09-11", label: "前天" },
      { date: "2026-09-12", label: "昨天" },
      { date: "2026-09-13", label: "今天" },
    ];
    const chartDays = days.map((day, index) => ({
      ...day,
      ...metrics({
        non_cached_input_tokens: 60 + index,
        cached_input_tokens: 40,
        output_tokens: 20,
        total_tokens: 120 + index,
      }),
    }));
    const wrapper = mount(DailyMetricChart, {
      props: { mode: "tokens", days, metrics: chartDays, title: "示例模型 Token 用量" },
    });

    expect(wrapper.findAll(".token-bar")).toHaveLength(3);
    expect(wrapper.findAll(".bar-track")[0].attributes("tabindex")).toBe("0");
    expect(wrapper.findAll(".bar-track")[0].attributes("aria-label")).toContain("非缓存输入 60");
    expect(wrapper.find("table caption").text()).toContain("示例模型 Token 用量数据");
  });
});
