<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
  buildAnalyticsParameters,
  emptyAnalyticsMetrics,
  shanghaiDate,
  sumAnalyticsMetrics,
  TIME_RANGE_OPTIONS,
  type TimeRange,
} from "../analytics";
import { fetchDailyAnalytics } from "../api";
import { formatNumber, formatTime } from "../format";
import type { AnalyticsDay, DailyAnalytics } from "../types";
import ModelTokenRanking from "./charts/ModelTokenRanking.vue";
import TokenTrendChart from "./charts/TokenTrendChart.vue";

const props = defineProps<{ refreshVersion: number }>();

const providerOptions = [
  { value: "ark_coding", label: "方舟 Coding Plan" },
  { value: "bailian", label: "阿里云百炼" },
  { value: "deepseek", label: "DeepSeek 官方" },
];
const analytics = ref<DailyAnalytics | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const range = ref<TimeRange>("30");
const provider = ref("");
const model = ref("");
const modelOptionsByProvider = ref<Record<string, string[]>>({});
const startDate = ref(shanghaiDate(29));
const endDate = ref(shanghaiDate());
let requestId = 0;

const metrics = computed(() => analytics.value?.totals ?? emptyAnalyticsMetrics());
const modelOptions = computed(() => {
  if (!provider.value) return [];
  return modelOptionsByProvider.value[provider.value] ?? [];
});
const trendDays = computed<AnalyticsDay[]>(() => (analytics.value?.days ?? []).map((day) => ({
  ...day,
  ...sumAnalyticsMetrics(
    analytics.value?.providers.map((item) => (
      item.days.find((entry) => entry.date === day.date) ?? emptyAnalyticsMetrics()
    )) ?? [],
  ),
})));
const rankingItems = computed(() => (analytics.value?.providers.flatMap((providerItem) => (
  providerItem.models
    .filter((item) => item.totals.total_tokens > 0)
    .map((item) => ({
      key: `${providerItem.provider}:${item.model}`,
      provider: providerItem.provider,
      providerName: providerItem.display_name,
      model: item.model,
      totalTokens: item.totals.total_tokens,
    }))
)) ?? []));
const summaryCards = computed(() => [
  { label: "总 Token", value: metrics.value.total_tokens, tone: "blue" },
  { label: "输入 Token", value: metrics.value.input_tokens, tone: "blue-soft" },
  { label: "非缓存输入", value: metrics.value.non_cached_input_tokens, tone: "blue" },
  { label: "缓存命中", value: metrics.value.cached_input_tokens, tone: "blue-soft" },
  { label: "输出 Token", value: metrics.value.output_tokens, tone: "green" },
]);

async function loadAnalytics(): Promise<void> {
  if (range.value === "custom" && (!startDate.value || !endDate.value)) return;
  const currentRequest = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const result = await fetchDailyAnalytics(buildAnalyticsParameters({
      range: range.value,
      startDate: startDate.value,
      endDate: endDate.value,
      provider: provider.value || undefined,
      model: model.value || undefined,
    }));
    if (currentRequest === requestId) {
      analytics.value = result;
      const nextOptions = { ...modelOptionsByProvider.value };
      for (const providerItem of result.providers) {
        const existing = nextOptions[providerItem.provider] ?? [];
        nextOptions[providerItem.provider] = [
          ...new Set([...existing, ...providerItem.models.map((item) => item.model)]),
        ];
      }
      modelOptionsByProvider.value = nextOptions;
    }
  } catch (caught) {
    if (currentRequest === requestId) {
      error.value = caught instanceof Error ? caught.message : "读取 Token 数据失败";
    }
  } finally {
    if (currentRequest === requestId) loading.value = false;
  }
}

function handleProviderChange(): void {
  model.value = "";
}

watch(
  [range, provider, model, startDate, endDate, () => props.refreshVersion],
  () => void loadAnalytics(),
  { immediate: true },
);
</script>

<template>
  <div class="provider-dashboard" :aria-busy="loading">
    <section class="analytics-toolbar" aria-label="Token 汇总筛选">
      <div class="filter-pills">
        <label class="filter-pill">
          <span>时间维度</span>
          <select v-model="range">
            <option v-for="option in TIME_RANGE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-pill">
          <span>Provider</span>
          <select v-model="provider" @change="handleProviderChange">
            <option value="">全部计划</option>
            <option v-for="option in providerOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-pill" :class="{ disabled: !provider }">
          <span>使用模型</span>
          <select v-model="model" :disabled="!provider">
            <option value="">{{ provider ? "全部模型" : "请先选择 Provider" }}</option>
            <option v-for="item in modelOptions" :key="item" :value="item">
              {{ item }}
            </option>
          </select>
        </label>
        <div v-if="range === 'custom'" class="custom-dates">
          <label><span>开始日期</span><input v-model="startDate" type="date" /></label>
          <span aria-hidden="true">—</span>
          <label><span>结束日期</span><input v-model="endDate" type="date" /></label>
        </div>
      </div>
      <div class="toolbar-context">
        <span>全局已上报用量</span>
        <strong v-if="analytics">{{ analytics.range.start }} 至 {{ analytics.range.end }}</strong>
        <small>更新时间 {{ formatTime(analytics?.generated_at) }}</small>
      </div>
    </section>

    <div v-if="error" class="error-banner" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="loadAnalytics">重新读取</button>
    </div>

    <section class="summary-strip summary-strip--five" aria-label="Token 总用量摘要">
      <article v-for="card in summaryCards" :key="card.label" :data-tone="card.tone">
        <span>{{ card.label }}</span>
        <strong>{{ loading ? "—" : formatNumber(card.value) }}</strong>
      </article>
    </section>

    <div v-if="metrics.usage_unknown_calls" class="coverage-notice" role="status">
      <strong>{{ formatNumber(metrics.usage_unknown_calls) }} 次调用未返回 Token 用量</strong>
      <span>排行和趋势只统计供应商已上报的 Token。</span>
    </div>

    <section class="chart-panel">
      <header class="chart-panel-heading">
        <div>
          <span class="section-kicker">GLOBAL TOKEN TREND</span>
          <h2>每日 Token 总量</h2>
        </div>
        <p>非缓存输入 + 缓存命中 + 输出</p>
      </header>
      <TokenTrendChart :days="trendDays" title="全局每日 Token 总量" />
    </section>

    <section class="chart-panel">
      <header class="chart-panel-heading">
        <div>
          <span class="section-kicker">MODEL RANKING</span>
          <h2>实际模型 Token 排行</h2>
        </div>
        <p>同名模型在不同 Provider 下分别统计</p>
      </header>
      <ModelTokenRanking :items="rankingItems" title="实际模型 Token 排行" />
    </section>
  </div>
</template>
