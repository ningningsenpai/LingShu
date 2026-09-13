<script setup lang="ts">
import { computed } from "vue";

import {
  chartColors,
  compactNumber,
  escapeHtml,
  tooltipIndex,
} from "./chartUtils";
import { useEChart } from "./echarts";

export interface ModelTokenRankingItem {
  key: string;
  provider: string;
  providerName: string;
  model: string;
  totalTokens: number;
}

const props = defineProps<{
  items: ModelTokenRankingItem[];
  title?: string;
}>();

const ranking = computed(() => [...props.items].sort((left, right) => (
  right.totalTokens - left.totalTokens || left.model.localeCompare(right.model)
)));

const chartHeight = computed(() => `${Math.max(240, ranking.value.length * 38 + 54)}px`);

const ariaLabel = computed(() => {
  if (!ranking.value.length) return `${props.title ?? "实际模型 Token 用量排行"}，暂无数据`;
  return `${props.title ?? "实际模型 Token 用量排行"}。${ranking.value.map((item, index) => (
    `第${index + 1}名，${item.providerName}的${item.model}，${item.totalTokens} Token`
  )).join("；")}`;
});

const { chartElement } = useEChart((reducedMotion) => {
  const reversed = [...ranking.value].reverse();
  return {
    animation: !reducedMotion,
    animationDuration: reducedMotion ? 0 : 420,
    animationEasing: "cubicOut",
    grid: { top: 12, right: 72, bottom: 28, left: 148 },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "rgba(255, 255, 255, 0.98)",
      borderColor: chartColors.line,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: chartColors.ink, fontSize: 12 },
      formatter: (parameters: unknown) => {
        const item = reversed[tooltipIndex(parameters)];
        if (!item) return "";
        return [
          `<strong>${escapeHtml(item.model)}</strong>`,
          `${escapeHtml(item.providerName)} · ${escapeHtml(item.provider)}`,
          `${compactNumber(item.totalTokens)} Token`,
        ].join("<br>");
      },
    },
    xAxis: {
      type: "value",
      min: 0,
      axisLabel: { color: chartColors.muted, formatter: compactNumber },
      splitLine: { lineStyle: { color: chartColors.line, type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: reversed.map((item) => item.model),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: chartColors.ink,
        fontFamily: "Cascadia Code, Consolas, monospace",
        fontSize: 11,
        width: 130,
        overflow: "truncate",
      },
    },
    series: [{
      name: "总 Token",
      type: "bar",
      data: reversed.map((item) => item.totalTokens),
      barMaxWidth: 18,
      label: {
        show: true,
        position: "right",
        color: chartColors.muted,
        fontSize: 10,
        formatter: (parameters: unknown) => {
          if (!parameters || typeof parameters !== "object" || !("value" in parameters)) return "";
          const value = (parameters as { value?: unknown }).value;
          return typeof value === "number" ? compactNumber(value) : "";
        },
      },
      itemStyle: { color: chartColors.blue, borderRadius: [0, 4, 4, 0] },
      emphasis: { itemStyle: { color: chartColors.green } },
    }],
  };
});
</script>

<template>
  <figure class="ranking-chart" :style="{ height: chartHeight }">
    <figcaption class="sr-only">{{ title ?? "实际模型 Token 用量排行" }}</figcaption>
    <div
      ref="chartElement"
      class="chart-canvas"
      role="img"
      tabindex="0"
      :aria-label="ariaLabel"
    ></div>
    <p v-if="!items.length" class="empty-state">暂无模型 Token 排行数据</p>
    <table class="sr-only">
      <caption>{{ title ?? "实际模型 Token 用量排行" }}数据</caption>
      <thead><tr><th>名次</th><th>Provider</th><th>实际模型</th><th>总 Token</th></tr></thead>
      <tbody>
        <tr v-for="(item, index) in ranking" :key="item.key">
          <td>{{ index + 1 }}</td>
          <td>{{ item.providerName }}</td>
          <td>{{ item.model }}</td>
          <td>{{ item.totalTokens }}</td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>

<style scoped>
.ranking-chart {
  position: relative;
  min-width: 0;
  min-height: 240px;
  margin: 0;
  border-radius: 10px;
  background: #fff;
}

.chart-canvas {
  width: 100%;
  height: 100%;
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
  .ranking-chart { min-height: 220px; }
}
</style>
