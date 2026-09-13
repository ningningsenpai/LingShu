<script setup lang="ts">
import { computed } from "vue";

import type { AnalyticsDay } from "../../types";
import {
  chartColors,
  compactNumber,
  dayLabel,
  escapeHtml,
  tooltipIndex,
} from "./chartUtils";
import { useEChart } from "./echarts";

const props = defineProps<{
  days: AnalyticsDay[];
  title?: string;
}>();

const ariaLabel = computed(() => {
  if (!props.days.length) return `${props.title ?? "模型调用次数趋势"}图，暂无数据`;
  const details = props.days.map((day, index) => (
    `${dayLabel(props.days, index).replace("\n", " ")}调用${day.attempts}次，响应${day.responded}次，成功${day.succeeded}次，结果未知${day.outcome_unknown}次`
  ));
  return `${props.title ?? "模型调用次数趋势"}图。${details.join("；")}`;
});

const { chartElement } = useEChart((reducedMotion) => ({
  animation: !reducedMotion,
  animationDuration: reducedMotion ? 0 : 480,
  animationEasing: "cubicOut",
  grid: { top: 24, right: 18, bottom: 48, left: 54 },
  tooltip: {
    trigger: "axis",
    confine: true,
    backgroundColor: "rgba(255, 255, 255, 0.98)",
    borderColor: chartColors.line,
    borderWidth: 1,
    padding: [10, 12],
    textStyle: { color: chartColors.ink, fontSize: 12 },
    axisPointer: { type: "line", lineStyle: { color: "#b9c7de", type: "dashed" } },
    formatter: (parameters: unknown) => {
      const day = props.days[tooltipIndex(parameters)];
      if (!day) return "";
      return [
        `<strong>${escapeHtml(day.date)}</strong>`,
        `调用 ${compactNumber(day.attempts)}`,
        `响应 ${compactNumber(day.responded)}`,
        `成功 ${compactNumber(day.succeeded)}`,
        `结果未知 ${compactNumber(day.outcome_unknown)}`,
      ].join("<br>");
    },
  },
  xAxis: {
    type: "category",
    boundaryGap: false,
    data: props.days.map((_, index) => dayLabel(props.days, index)),
    axisLine: { lineStyle: { color: chartColors.line } },
    axisTick: { show: false },
    axisLabel: { color: chartColors.muted, fontSize: 11, lineHeight: 17 },
  },
  yAxis: {
    type: "value",
    min: 0,
    minInterval: 1,
    axisLabel: { color: chartColors.muted, formatter: compactNumber },
    splitLine: { lineStyle: { color: chartColors.line, type: "dashed" } },
  },
  series: [{
    name: "调用尝试",
    type: "line",
    data: props.days.map((day) => day.attempts),
    smooth: false,
    showSymbol: true,
    symbol: "circle",
    symbolSize: 8,
    lineStyle: { color: chartColors.blue, width: 2.5 },
    itemStyle: { color: "#ffffff", borderColor: chartColors.blue, borderWidth: 3 },
    areaStyle: { color: chartColors.blueSoft, opacity: 1 },
    emphasis: { focus: "series", scale: 1.2 },
  }],
}));
</script>

<template>
  <figure class="trend-chart">
    <figcaption class="sr-only">{{ title ?? "模型调用次数趋势" }}</figcaption>
    <div
      ref="chartElement"
      class="chart-canvas"
      role="img"
      tabindex="0"
      :aria-label="ariaLabel"
    ></div>
    <p v-if="!days.length" class="empty-state">暂无调用趋势数据</p>
    <table class="sr-only">
      <caption>{{ title ?? "模型调用次数趋势" }}数据</caption>
      <thead><tr><th>日期</th><th>调用</th><th>响应</th><th>成功</th><th>结果未知</th></tr></thead>
      <tbody>
        <tr v-for="day in days" :key="day.date">
          <th>{{ day.date }}</th>
          <td>{{ day.attempts }}</td>
          <td>{{ day.responded }}</td>
          <td>{{ day.succeeded }}</td>
          <td>{{ day.outcome_unknown }}</td>
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

.chart-canvas {
  width: 100%;
  height: 300px;
  outline: none;
}

.chart-canvas:focus-visible {
  border-radius: 8px;
  box-shadow: inset 0 0 0 2px #315bf5;
}

.empty-state {
  position: absolute;
  inset: 50% 0 auto;
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
  .chart-canvas { height: 260px; }
}
</style>
