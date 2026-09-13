<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
  buildAnalyticsParameters,
  emptyAnalyticsMetrics,
  shanghaiDate,
  TIME_RANGE_OPTIONS,
  type TimeRange,
} from "../analytics";
import { fetchDailyAnalytics } from "../api";
import { formatNumber, formatTime } from "../format";
import type { AnalyticsModel, DailyAnalytics } from "../types";
import CallTrendChart from "./charts/CallTrendChart.vue";
import TokenTrendChart from "./charts/TokenTrendChart.vue";

const props = defineProps<{
  providerKey: string;
  displayName: string;
  refreshVersion: number;
}>();

const analytics = ref<DailyAnalytics | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const range = ref<TimeRange>("30");
const model = ref("");
const modelOptions = ref<string[]>([]);
const startDate = ref(shanghaiDate(29));
const endDate = ref(shanghaiDate());
let requestId = 0;

const provider = computed(() => analytics.value?.providers.find(
  (item) => item.provider === props.providerKey,
));
const metrics = computed(() => analytics.value?.totals ?? emptyAnalyticsMetrics());
const visibleModels = computed(() => {
  const items = provider.value?.models ?? [];
  if (!model.value) return items;
  return items.filter((item) => item.model === model.value);
});
const rangeLabel = computed(() => {
  if (!analytics.value) return "读取中";
  return `${analytics.value.range.start} 至 ${analytics.value.range.end}`;
});
const summaryCards = computed(() => [
  { label: "调用次数", value: metrics.value.attempts, tone: "blue" },
  { label: "响应次数", value: metrics.value.responded, tone: "green" },
  { label: "成功次数", value: metrics.value.succeeded, tone: "green" },
  { label: "总 Token", value: metrics.value.total_tokens, tone: "blue" },
  { label: "输入 Token", value: metrics.value.input_tokens, tone: "blue-soft" },
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
      provider: props.providerKey,
      model: model.value || undefined,
    }));
    if (currentRequest === requestId) {
      analytics.value = result;
      const currentModels = result.providers.find(
        (item) => item.provider === props.providerKey,
      )?.models.map((item) => item.model) ?? [];
      modelOptions.value = [...new Set([...modelOptions.value, ...currentModels])];
    }
  } catch (caught) {
    if (currentRequest === requestId) {
      error.value = caught instanceof Error ? caught.message : "读取分析数据失败";
    }
  } finally {
    if (currentRequest === requestId) loading.value = false;
  }
}

function aliases(item: AnalyticsModel): string {
  return item.aliases.length ? item.aliases.join("、") : "无别名";
}

watch(
  [range, model, startDate, endDate, () => props.refreshVersion],
  () => void loadAnalytics(),
  { immediate: true },
);
</script>

<template>
  <div class="provider-dashboard" :aria-busy="loading">
    <section class="analytics-toolbar" aria-label="分析筛选">
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
          <span>使用模型</span>
          <select v-model="model">
            <option value="">全部模型</option>
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
        <span>{{ provider?.configured ? "本机已配置" : "本机未配置" }}</span>
        <strong>{{ rangeLabel }}</strong>
        <small>更新时间 {{ formatTime(analytics?.generated_at) }}</small>
      </div>
    </section>

    <div v-if="error" class="error-banner" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="loadAnalytics">重新读取</button>
    </div>

    <section class="summary-strip" :aria-label="`${displayName} 汇总指标`">
      <article v-for="card in summaryCards" :key="card.label" :data-tone="card.tone">
        <span>{{ card.label }}</span>
        <strong>{{ loading ? "—" : formatNumber(card.value) }}</strong>
      </article>
    </section>

    <div v-if="metrics.usage_unknown_calls" class="coverage-notice" role="status">
      <strong>{{ formatNumber(metrics.usage_unknown_calls) }} 次调用未返回 Token 用量</strong>
      <span>图表只统计已上报的 Token，未知用量不会被当作零。</span>
    </div>

    <section class="chart-panel">
      <header class="chart-panel-heading">
        <div>
          <span class="section-kicker">CALL TREND</span>
          <h2>每日调用次数</h2>
        </div>
        <p>{{ model || "全部模型汇总" }} · Asia/Shanghai</p>
      </header>
      <CallTrendChart
        :days="provider?.days ?? []"
        :title="`${displayName} 每日调用次数`"
      />
    </section>

    <section class="chart-panel">
      <header class="chart-panel-heading">
        <div>
          <span class="section-kicker">TOKEN COMPOSITION</span>
          <h2>每日 Token 构成</h2>
        </div>
        <p>输入总量包含缓存命中部分</p>
      </header>
      <TokenTrendChart
        :days="provider?.days ?? []"
        :title="`${displayName} 每日 Token 构成`"
      />
    </section>

    <details class="model-details">
      <summary>
        <span>模型数据明细</span>
        <small>{{ visibleModels.length }} 个实际模型</small>
      </summary>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">实际模型</th>
              <th scope="col">别名</th>
              <th scope="col">调用</th>
              <th scope="col">响应</th>
              <th scope="col">输入</th>
              <th scope="col">缓存命中</th>
              <th scope="col">输出</th>
              <th scope="col">总 Token</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in visibleModels" :key="item.key">
              <td><code>{{ item.model }}</code></td>
              <td>{{ aliases(item) }}</td>
              <td>{{ formatNumber(item.totals.attempts) }}</td>
              <td>{{ formatNumber(item.totals.responded) }}</td>
              <td>{{ formatNumber(item.totals.input_tokens) }}</td>
              <td>{{ formatNumber(item.totals.cached_input_tokens) }}</td>
              <td>{{ formatNumber(item.totals.output_tokens) }}</td>
              <td>{{ formatNumber(item.totals.total_tokens) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>
</template>
