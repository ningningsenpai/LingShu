<script setup lang="ts">
import { computed } from "vue";

import type { AnalyticsDay } from "../../types";
import {
  chartColors,
  compactNumber,
  dayLabel,
  escapeHtml,
  knownTokenTotal,
  tooltipIndex,
} from "./chartUtils";
import { useEChart } from "./echarts";

const props = defineProps<{
  days: AnalyticsDay[];
  title?: string;
}>();

const ariaLabel = computed(() => {
  if (!props.days.length) return `${props.title ?? "Token 用量"}堆叠柱状图，暂无数据`;
  const details = props.days.map((day, index) => (
    `${dayLabel(props.days, index).replace("\n", " ")}总 Token ${knownTokenTotal(day)}，非缓存输入${day.non_cached_input_tokens}，缓存输入${day.cached_input_tokens}，输出${day.output_tokens}`
  ));
  return `${props.title ?? "Token 用量"}堆叠柱状图。${details.join("；")}`;
});

const { chartElement } = useEChart((reducedMotion) => ({
  animation: !reducedMotion,
  animationDuration: reducedMotion ? 0 : 440,
  animationEasing: "cubicOut",
  grid: { top: 26, right: 18, bottom: 48, left: 58 },
  tooltip: {
    trigger: "axis",
    confine: true,
    axisPointer: { type: "shadow", shadowStyle: { color: "rgba(49, 91, 245, 0.05)" } },
    backgroundColor: "rgba(255, 255, 255, 0.98)",
    borderColor: chartColors.line,
    borderWidth: 1,
    padding: [10, 12],
    textStyle: { color: chartColors.ink, fontSize: 12 },
    formatter: (parameters: unknown) => {
      const day = props.days[tooltipIndex(parameters)];
      if (!day) return "";
      return [
        `<strong>${escapeHtml(day.date)} · ${compactNumber(knownTokenTotal(day))} Token</strong>`,
        `非缓存输入 ${compactNumber(day.non_cached_input_tokens)}`,
        `缓存输入 ${compactNumber(day.cached_input_tokens)}`,
        `输出 ${compactNumber(day.output_tokens)}`,
      ].join("<br>");
    },
  },
  xAxis: {
    type: "category",
    data: props.days.map((_, index) => dayLabel(props.days, index)),
    axisLine: { lineStyle: { color: chartColors.line } },
    axisTick: { show: false },
    axisLabel: { color: chartColors.muted, fontSize: 11, lineHeight: 17 },
  },
  yAxis: {
    type: "value",
    min: 0,
    axisLabel: { color: chartColors.muted, formatter: compactNumber },
    splitLine: { lineStyle: { color: chartColors.line, type: "dashed" } },
  },
  series: [
    {
      name: "非缓存输入",
      type: "bar",
      stack: "tokens",
      barMaxWidth: 48,
      data: props.days.map((day) => day.non_cached_input_tokens),
      itemStyle: { color: chartColors.blue },
      emphasis: { focus: "series" },
    },
    {
      name: "缓存输入",
      type: "bar",
      stack: "tokens",
      barMaxWidth: 48,
      data: props.days.map((day) => day.cached_input_tokens),
      itemStyle: { color: chartColors.cached },
      emphasis: { focus: "series" },
    },
    {
      name: "输出",
      type: "bar",
      stack: "tokens",
      barMaxWidth: 48,
      data: props.days.map((day) => day.output_tokens),
      itemStyle: { color: chartColors.green, borderRadius: [4, 4, 0, 0] },
      emphasis: { focus: "series" },
    },
  ],
}));
</script>

<template>
  <figure class="trend-chart">
    <figcaption class="chart-legend" aria-hidden="true">
      <span><i data-series="input"></i>非缓存输入</span>
      <span><i data-series="cached"></i>缓存输入</span>
      <span><i data-series="output"></i>输出</span>
    </figcaption>
    <div
      ref="chartElement"
      class="chart-canvas"
      role="img"
      tabindex="0"
      :aria-label="ariaLabel"
    ></div>
    <p v-if="!days.length" class="empty-state">暂无 Token 用量数据</p>
    <table class="sr-only">
      <caption>{{ title ?? "Token 用量" }}堆叠柱状图数据</caption>
      <thead><tr><th>日期</th><th>非缓存输入</th><th>缓存输入</th><th>输出</th><th>总 Token</th></tr></thead>
      <tbody>
        <tr v-for="day in days" :key="day.date">
          <th>{{ day.date }}</th>
          <td>{{ day.non_cached_input_tokens }}</td>
          <td>{{ day.cached_input_tokens }}</td>
          <td>{{ day.output_tokens }}</td>
          <td>{{ knownTokenTotal(day) }}</td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>

<style scoped>
.trend-chart {
  position: relative;
  min-width: 0;
  margin: 0;
  border-radius: 10px;
  background: #fff;
}

.chart-legend {
  display: flex;
  min-height: 22px;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
  color: #68758c;
  font-size: 11px;
}

.chart-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.chart-legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: #315bf5;
}

.chart-legend i[data-series="cached"] { background: #9bb5ff; }
.chart-legend i[data-series="output"] { background: #18a875; }

.chart-canvas {
  width: 100%;
  height: 278px;
  outline: none;
}

.chart-canvas:focus-visible {
  border-radius: 8px;
  box-shadow: inset 0 0 0 2px #315bf5;
}

.empty-state {
  position: absolute;
  inset: 52% 0 auto;
  margin: 0;
  color: #68758c;
  font-size: 12px;
  text-align: center;
  transform: translateY(-50%);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 640px) {
  .chart-legend { justify-content: flex-start; }
  .chart-canvas { height: 238px; }
}
</style>
