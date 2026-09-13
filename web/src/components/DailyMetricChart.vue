<script setup lang="ts">
import { computed } from "vue";

import { barHeight, chartMaximum, emptyAnalyticsMetrics, tokenParts } from "../analytics";
import { formatNumber } from "../format";
import type { AnalyticsDay, AnalyticsMetrics, DailyAnalytics } from "../types";

const props = defineProps<{
  mode: "calls" | "tokens";
  days: DailyAnalytics["days"];
  metrics: AnalyticsDay[];
  title: string;
}>();

const chartDays = computed(() => props.days.map((day) => ({
  ...day,
  metrics: props.metrics.find((item) => item.date === day.date) ?? emptyAnalyticsMetrics(),
})));

const maximum = computed(() => chartMaximum(
  chartDays.value.map((day) => day.metrics),
  props.mode,
));

function valueFor(metrics: AnalyticsMetrics): number {
  return props.mode === "calls" ? metrics.attempts : metrics.total_tokens;
}

function barStyle(metrics: AnalyticsMetrics): Record<string, string> {
  return { height: `${barHeight(valueFor(metrics), maximum.value)}%` };
}

function segmentStyle(value: number, total: number): Record<string, string> {
  return { height: `${total > 0 ? (value / total) * 100 : 0}%` };
}

function accessibleLabel(label: string, metrics: AnalyticsMetrics): string {
  if (props.mode === "calls") {
    return `${label}，调用 ${formatNumber(metrics.attempts)} 次，收到响应 ${formatNumber(metrics.responded)} 次，结果未知 ${formatNumber(metrics.outcome_unknown)} 次`;
  }
  return `${label}，已上报 Token 共 ${formatNumber(metrics.total_tokens)}，非缓存输入 ${formatNumber(metrics.non_cached_input_tokens)}，缓存输入 ${formatNumber(metrics.cached_input_tokens)}，输出 ${formatNumber(metrics.output_tokens)}，${formatNumber(metrics.usage_unknown_calls)} 次调用用量未知`;
}
</script>

<template>
  <figure class="daily-chart">
    <figcaption class="sr-only">{{ title }}</figcaption>
    <div class="chart-stage">
      <div class="chart-gridlines" aria-hidden="true"><i></i><i></i><i></i></div>
      <div class="chart-columns">
        <div v-for="day in chartDays" :key="day.date" class="chart-column">
          <span class="chart-value">{{ formatNumber(valueFor(day.metrics)) }}</span>
          <div
            class="bar-track"
            role="img"
            tabindex="0"
            :aria-label="accessibleLabel(day.label, day.metrics)"
          >
            <div
              v-if="mode === 'calls'"
              class="call-bar"
              :class="{ 'is-empty': day.metrics.attempts === 0 }"
              :style="barStyle(day.metrics)"
            ></div>
            <div
              v-else
              class="token-bar"
              :class="{ 'is-empty': day.metrics.total_tokens === 0 }"
              :style="barStyle(day.metrics)"
            >
              <span
                v-for="part in tokenParts(day.metrics)"
                :key="part.key"
                :class="`token-segment token-segment--${part.key}`"
                :style="segmentStyle(part.value, day.metrics.total_tokens)"
              ></span>
            </div>
          </div>
          <strong>{{ day.label }}</strong>
          <span class="chart-date">{{ day.date.slice(5) }}</span>
          <span
            v-if="mode === 'tokens' && day.metrics.usage_unknown_calls"
            class="chart-unknown"
          >
            {{ formatNumber(day.metrics.usage_unknown_calls) }} 次未知
          </span>
        </div>
      </div>
    </div>

    <table class="sr-only">
      <caption>{{ title }}数据</caption>
      <thead>
        <tr>
          <th>日期</th>
          <th v-if="mode === 'calls'">调用次数</th>
          <template v-else>
            <th>非缓存输入</th>
            <th>缓存输入</th>
            <th>输出</th>
            <th>总 Token</th>
            <th>用量未知调用</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr v-for="day in chartDays" :key="day.date">
          <th>{{ day.label }} {{ day.date }}</th>
          <td v-if="mode === 'calls'">{{ day.metrics.attempts }}</td>
          <template v-else>
            <td>{{ day.metrics.non_cached_input_tokens }}</td>
            <td>{{ day.metrics.cached_input_tokens }}</td>
            <td>{{ day.metrics.output_tokens }}</td>
            <td>{{ day.metrics.total_tokens }}</td>
            <td>{{ day.metrics.usage_unknown_calls }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
