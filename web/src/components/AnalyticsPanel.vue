<script setup lang="ts">
import { computed } from "vue";

import { sumAnalyticsMetrics } from "../analytics";
import { formatNumber } from "../format";
import type { DailyAnalytics } from "../types";
import DailyMetricChart from "./DailyMetricChart.vue";

const props = defineProps<{
  analytics: DailyAnalytics | null;
  mode: "calls" | "tokens";
  loading: boolean;
  error: string | null;
}>();

const totals = computed(() => sumAnalyticsMetrics(
  props.analytics?.providers.map((provider) => provider.totals) ?? [],
));

const isEmpty = computed(() => totals.value.attempts === 0);

const summaryCards = computed(() => props.mode === "calls" ? [
  { label: "调用尝试", value: totals.value.attempts, tone: "blue" },
  { label: "确认响应", value: totals.value.responded, tone: "green" },
  { label: "成功完成", value: totals.value.succeeded, tone: "green" },
  { label: "结果未知", value: totals.value.outcome_unknown, tone: "warning" },
] : [
  { label: "Token 总量", value: totals.value.total_tokens, tone: "blue" },
  { label: "非缓存输入", value: totals.value.non_cached_input_tokens, tone: "blue" },
  { label: "缓存输入", value: totals.value.cached_input_tokens, tone: "neutral" },
  { label: "输出", value: totals.value.output_tokens, tone: "green" },
]);

function pricingLabel(mode: string): string {
  if (mode === "SUBSCRIPTION") return "套餐额度";
  if (mode === "METERED") return "按量计费";
  if (mode === "MIXED") return "混合计价";
  return "计价未知";
}
</script>

<template>
  <div class="analytics-view">
    <div v-if="error" class="error-banner" role="alert">
      <span>{{ error }}</span>
      <span>自动刷新会继续尝试连接</span>
    </div>

    <section class="analytics-summary" :aria-label="mode === 'calls' ? '三日调用摘要' : '三日 Token 摘要'">
      <article v-for="card in summaryCards" :key="card.label" :data-tone="card.tone">
        <span>{{ card.label }}</span>
        <strong>{{ loading ? "—" : formatNumber(card.value) }}</strong>
      </article>
    </section>

    <div v-if="mode === 'tokens' && totals.usage_unknown_calls > 0" class="coverage-notice" role="status">
      <strong>{{ formatNumber(totals.usage_unknown_calls) }} 次调用未返回用量</strong>
      <span>图表仅统计已上报 Token，未知用量不会被当作零值。</span>
    </div>

    <section class="analytics-panel" aria-labelledby="analytics-heading">
      <header class="analytics-heading">
        <div>
          <p class="section-kicker">PROVIDER / MODEL / DAY</p>
          <h2 id="analytics-heading">
            {{ mode === "calls" ? "三日调用分布" : "三日 Token 构成" }}
          </h2>
        </div>
        <div v-if="mode === 'tokens'" class="chart-legend" aria-label="Token 图例">
          <span><i data-series="non-cached"></i>非缓存输入</span>
          <span><i data-series="cached"></i>缓存输入</span>
          <span><i data-series="output"></i>输出</span>
        </div>
        <span v-else class="chart-context">柱高表示每日调用尝试次数</span>
      </header>

      <div v-if="loading" class="analytics-skeleton" aria-label="正在读取分析数据">
        <span v-for="index in 3" :key="index"></span>
      </div>

      <template v-else-if="analytics">
        <div v-if="isEmpty" class="analytics-empty">
          <div class="empty-orbit" aria-hidden="true"><span></span></div>
          <div>
            <strong>最近三天没有模型调用</strong>
            <p>下方仍列出本机可用的 Provider 与实际模型。</p>
          </div>
        </div>

        <section
          v-for="provider in analytics.providers"
          :key="provider.provider"
          class="provider-group"
          :aria-labelledby="`provider-${provider.provider}`"
        >
          <header class="provider-heading">
            <div class="provider-title">
              <span class="provider-signal" :class="{ muted: !provider.configured }" aria-hidden="true"></span>
              <div>
                <h3 :id="`provider-${provider.provider}`">{{ provider.display_name }}</h3>
                <code>{{ provider.provider }}</code>
              </div>
            </div>
            <div class="provider-totals">
              <span :class="{ unconfigured: !provider.configured }">
                {{ provider.configured ? "本机已配置" : "本机未配置" }}
              </span>
              <strong>
                {{ formatNumber(mode === "calls" ? provider.totals.attempts : provider.totals.total_tokens) }}
                <small>{{ mode === "calls" ? "次调用" : "Token" }}</small>
              </strong>
            </div>
          </header>

          <div v-if="provider.models.length" class="model-list">
            <article v-for="model in provider.models" :key="model.key" class="model-row">
              <header class="model-identity">
                <span class="model-kicker">ACTUAL MODEL</span>
                <h4>{{ model.model }}</h4>
                <div class="alias-list">
                  <span v-for="alias in model.aliases" :key="alias">{{ alias }}</span>
                  <span v-if="!model.aliases.length">无别名</span>
                </div>
                <p>{{ pricingLabel(model.pricing_mode) }}</p>
                <dl>
                  <div>
                    <dt>{{ mode === "calls" ? "三日调用" : "三日 Token" }}</dt>
                    <dd>{{ formatNumber(mode === "calls" ? model.totals.attempts : model.totals.total_tokens) }}</dd>
                  </div>
                  <div>
                    <dt>{{ mode === "calls" ? "收到响应" : "用量上报" }}</dt>
                    <dd v-if="mode === 'calls'">{{ formatNumber(model.totals.responded) }}</dd>
                    <dd v-else>
                      {{ formatNumber(model.totals.usage_known_calls) }} 已知
                      <span v-if="model.totals.usage_unknown_calls">
                        · {{ formatNumber(model.totals.usage_unknown_calls) }} 未知
                      </span>
                    </dd>
                  </div>
                </dl>
              </header>
              <DailyMetricChart
                :mode="mode"
                :days="analytics.days"
                :metrics="model.days"
                :title="`${provider.display_name} ${model.model} ${mode === 'calls' ? '调用次数' : 'Token 用量'}`"
              />
            </article>
          </div>
          <p v-else class="provider-empty">该 Provider 暂无可展示模型。</p>
        </section>

        <p class="analytics-footnote">
          数据时区 {{ analytics.timezone }} · 统计范围为前天、昨天与今天 · 不包含 doctor 等非任务探测调用
        </p>
      </template>
    </section>
  </div>
</template>
