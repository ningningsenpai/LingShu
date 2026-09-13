<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";

import { fetchOverview, fetchTask, fetchTasks } from "./api";
import ProviderAnalyticsView from "./components/ProviderAnalyticsView.vue";
import TokenOverviewView from "./components/TokenOverviewView.vue";
import {
  callStateLabel,
  dispatchLabel,
  formatDuration,
  formatNumber,
  formatTime,
  taskStatusLabel,
} from "./format";
import type { Overview, TaskDetail, TaskSummary } from "./types";

type ViewId = "tasks" | "ark_coding" | "bailian" | "deepseek" | "tokens";

const providerOptions = [
  { provider: "ark_coding", display_name: "方舟 Coding Plan" },
  { provider: "bailian", display_name: "阿里云百炼" },
  { provider: "deepseek", display_name: "DeepSeek 官方" },
];
const navItems: Array<{ id: ViewId; label: string; symbol: string }> = [
  { id: "tasks", label: "任务历史", symbol: "▤" },
  { id: "ark_coding", label: "方舟 Coding Plan", symbol: "A" },
  { id: "bailian", label: "阿里云百炼", symbol: "B" },
  { id: "deepseek", label: "DeepSeek 官方", symbol: "D" },
  { id: "tokens", label: "Token 总用量", symbol: "Σ" },
];

const overview = ref<Overview | null>(null);
const tasks = ref<TaskSummary[]>([]);
const selectedTask = ref<TaskDetail | null>(null);
const activeView = ref<ViewId>("tasks");
const loading = ref(true);
const refreshing = ref(false);
const detailLoading = ref(false);
const error = ref<string | null>(null);
const navOpen = ref(false);
const refreshVersion = ref(0);
const statusFilter = ref("");
const providerFilter = ref("");
const searchFilter = ref("");
const closeButton = ref<HTMLButtonElement | null>(null);
const mainHeading = ref<HTMLHeadingElement | null>(null);
const taskDrawer = ref<HTMLElement | null>(null);
const taskTrigger = ref<HTMLElement | null>(null);
let refreshTimer: number | undefined;

const totalTokens = computed(() => {
  if (!overview.value) return 0;
  return overview.value.tokens.input + overview.value.tokens.output;
});

const connectionLabel = computed(() => {
  if (error.value) return "部分数据异常";
  if (refreshing.value) return "同步中";
  return "本机已连接";
});

const pageCopy: Record<ViewId, { kicker: string; title: string; description: string }> = {
  tasks: {
    kicker: "TASK HISTORY",
    title: "任务历史",
    description: "任务结果与供应商调用事实分开记录，避免把超时误判为“没有调用”。",
  },
  ark_coding: {
    kicker: "ARK CODING PLAN",
    title: "方舟 Coding Plan",
    description: "按时间与实际模型查看方舟套餐通道的调用趋势和 Token 构成。",
  },
  bailian: {
    kicker: "ALIBABA MODEL STUDIO",
    title: "阿里云百炼",
    description: "按时间与实际模型查看百炼通道的调用趋势和 Token 构成。",
  },
  deepseek: {
    kicker: "DEEPSEEK OFFICIAL",
    title: "DeepSeek 官方",
    description: "按时间与实际模型查看 DeepSeek 官方通道的调用趋势和 Token 构成。",
  },
  tokens: {
    kicker: "GLOBAL TOKEN LEDGER",
    title: "Token 总用量",
    description: "跨 Provider 查看每日 Token 构成，并比较实际模型的累计用量。",
  },
};

const currentPage = computed(() => pageCopy[activeView.value]);

const generatedAt = computed(() => overview.value?.generated_at);

async function loadData(silent = false): Promise<void> {
  if (silent) refreshing.value = true;
  else loading.value = true;
  const parameters = new URLSearchParams({ limit: "100" });
  if (statusFilter.value) parameters.set("status", statusFilter.value);
  if (providerFilter.value) parameters.set("provider", providerFilter.value);
  if (searchFilter.value.trim()) parameters.set("search", searchFilter.value.trim());
  try {
    const [overviewResult, taskResult] = await Promise.all([
      fetchOverview(),
      fetchTasks(parameters),
    ]);
    overview.value = overviewResult;
    tasks.value = taskResult.items;
    error.value = null;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "读取观测数据失败";
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

function scheduleRefresh(): void {
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(async () => {
    refreshing.value = true;
    await loadData(true);
    refreshing.value = false;
    scheduleRefresh();
  }, document.hidden ? 10_000 : 2_000);
}

async function refreshNow(): Promise<void> {
  refreshing.value = true;
  await loadData(true);
  refreshVersion.value += 1;
  refreshing.value = false;
  scheduleRefresh();
}

async function refreshTasks(): Promise<void> {
  await loadData(true);
  scheduleRefresh();
}

async function selectView(view: ViewId): Promise<void> {
  activeView.value = view;
  navOpen.value = false;
  await nextTick();
  mainHeading.value?.focus();
}

async function openTask(taskId: string, event?: Event): Promise<void> {
  taskTrigger.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
  detailLoading.value = true;
  selectedTask.value = null;
  try {
    selectedTask.value = await fetchTask(taskId);
    await nextTick();
    closeButton.value?.focus();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "读取任务详情失败";
  } finally {
    detailLoading.value = false;
  }
}

function closeTask(): void {
  selectedTask.value = null;
  void nextTick(() => taskTrigger.value?.focus());
}

function clearFilters(): void {
  statusFilter.value = "";
  providerFilter.value = "";
  searchFilter.value = "";
  void refreshTasks();
}

function taskTone(status: string): string {
  if (status === "ACCEPTED") return "success";
  if (status === "FAILED") return "danger";
  if (status === "DISPATCHED") return "active";
  return "neutral";
}

function dispatchTone(status: string): string {
  if (status === "RESPONDED") return "success";
  if (status === "ATTEMPTING") return "active";
  if (status === "OUTCOME_UNKNOWN") return "warning";
  return "neutral";
}

function callTone(status: string): string {
  if (status === "SUCCEEDED") return "success";
  if (status === "ATTEMPTING") return "active";
  if (status === "STALE" || status === "TIMED_OUT" || status === "NETWORK_ERROR") {
    return "warning";
  }
  return "danger";
}

function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape" && selectedTask.value) {
    closeTask();
    return;
  }
  if (event.key === "Escape" && navOpen.value) {
    navOpen.value = false;
    return;
  }
  if (event.key !== "Tab" || !selectedTask.value || !taskDrawer.value) return;
  const focusable = [...taskDrawer.value.querySelectorAll<HTMLElement>(
    "button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
  )].filter((element) => !element.hasAttribute("disabled"));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

onMounted(async () => {
  await loadData();
  scheduleRefresh();
  document.addEventListener("visibilitychange", scheduleRefresh);
  window.addEventListener("keydown", handleEscape);
});

onUnmounted(() => {
  window.clearTimeout(refreshTimer);
  document.removeEventListener("visibilitychange", scheduleRefresh);
  window.removeEventListener("keydown", handleEscape);
});
</script>

<template>
  <div class="app-shell">
    <div v-if="navOpen" class="sidebar-backdrop" @click="navOpen = false"></div>
    <aside class="app-sidebar" :class="{ open: navOpen }">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></div>
        <div class="brand-copy">
          <p class="eyebrow">LINGSHU / LOCAL</p>
          <p class="brand-name">模型观测台</p>
        </div>
      </div>

      <nav class="primary-nav" aria-label="主要导航">
        <button
          v-for="item in navItems"
          :key="item.id"
          type="button"
          :class="{ active: activeView === item.id }"
          :aria-current="activeView === item.id ? 'page' : undefined"
          @click="selectView(item.id)"
        >
          <span class="nav-symbol" aria-hidden="true">{{ item.symbol }}</span>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="sidebar-status" :class="{ offline: Boolean(error) }">
        <span class="connection-dot" aria-hidden="true"></span>
        <div>
          <strong>{{ connectionLabel }}</strong>
          <span>单用户 · 本机数据</span>
        </div>
      </div>
    </aside>

    <div class="content-shell">
      <header class="app-header">
        <button
          class="mobile-menu-button"
          type="button"
          aria-label="打开导航"
          :aria-expanded="navOpen"
          @click="navOpen = !navOpen"
        >
          <span></span><span></span><span></span>
        </button>
        <div class="mobile-brand">
          <div class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></div>
          <strong>灵枢</strong>
        </div>
        <div class="header-context">
          <span>{{ currentPage.title }}</span>
          <small>数据时间 {{ formatTime(generatedAt) }}</small>
        </div>
        <div class="header-actions">
          <div class="connection-state" :class="{ offline: Boolean(error) }">
            <span class="connection-dot" aria-hidden="true"></span>
            {{ connectionLabel }}
          </div>
          <button class="icon-button" type="button" aria-label="立即刷新" @click="refreshNow">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7" />
            </svg>
          </button>
        </div>
      </header>

      <main class="page-frame">
      <section class="page-intro" aria-labelledby="page-title">
        <div>
          <p class="section-kicker">{{ currentPage.kicker }}</p>
          <h1 id="page-title" ref="mainHeading" tabindex="-1">{{ currentPage.title }}</h1>
          <p>{{ currentPage.description }}</p>
        </div>
        <div v-if="activeView === 'tasks'" class="live-summary">
          <span class="pulse-ring" aria-hidden="true"></span>
          <div>
            <strong v-if="overview?.calls.attempting">
              {{ overview.calls.attempting }} 次派发正在等待响应
            </strong>
            <strong v-else>当前没有等待中的派发</strong>
            <span>数据时间 {{ formatTime(overview?.generated_at) }}</span>
          </div>
        </div>
      </section>

      <div v-if="activeView === 'tasks' && error" class="error-banner" role="alert">
        <span>{{ error }}</span>
        <button type="button" @click="refreshNow">重试连接</button>
      </div>

      <template v-if="activeView === 'tasks'">
      <section class="metric-grid" aria-label="核心指标">
        <article class="metric-card metric-card--blue">
          <div class="metric-label"><span>任务</span><span class="metric-index">01</span></div>
          <strong>{{ loading ? "—" : formatNumber(overview?.tasks.total) }}</strong>
          <p>{{ formatNumber(overview?.tasks.accepted) }} 完成 · {{ formatNumber(overview?.tasks.failed) }} 失败</p>
        </article>
        <article class="metric-card metric-card--green">
          <div class="metric-label"><span>调用响应</span><span class="metric-index">02</span></div>
          <strong>{{ loading ? "—" : formatNumber(overview?.calls.responded) }}</strong>
          <p>{{ formatNumber(overview?.calls.outcome_unknown) }} 次结果未知</p>
        </article>
        <article class="metric-card">
          <div class="metric-label"><span>已上报 Token</span><span class="metric-index">03</span></div>
          <strong>{{ loading ? "—" : formatNumber(totalTokens) }}</strong>
          <p>
            输入 {{ formatNumber(overview?.tokens.input) }} ·
            {{ formatNumber(overview?.tokens.unknown_calls) }} 次用量未知
          </p>
        </article>
      </section>

      <section class="workspace-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">TASK STREAM</p>
            <h2>任务轨迹</h2>
          </div>
          <div class="filters" aria-label="任务筛选">
            <label>
              <span>任务状态</span>
              <select v-model="statusFilter" @change="refreshTasks">
                <option value="">全部</option>
                <option value="ACCEPTED">已完成</option>
                <option value="FAILED">失败</option>
                <option value="DISPATCHED">执行中</option>
              </select>
            </label>
            <label>
              <span>Provider</span>
              <select v-model="providerFilter" @change="refreshTasks">
                <option value="">全部</option>
                <option
                  v-for="provider in providerOptions"
                  :key="provider.provider"
                  :value="provider.provider"
                >
                  {{ provider.display_name }}
                </option>
              </select>
            </label>
            <label class="search-field">
              <span>搜索</span>
              <input
                v-model="searchFilter"
                type="search"
                placeholder="任务 ID 或模型"
                @keyup.enter="refreshTasks"
              />
            </label>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">任务 / 时间</th>
                <th scope="col">模型</th>
                <th scope="col">任务结果</th>
                <th scope="col">调用事实</th>
                <th scope="col">Token</th>
                <th scope="col"><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody v-if="loading">
              <tr v-for="index in 5" :key="index" class="skeleton-row">
                <td colspan="6"><span></span></td>
              </tr>
            </tbody>
            <tbody v-else-if="tasks.length">
              <tr
                v-for="task in tasks"
                :key="task.task_id"
                role="button"
                tabindex="0"
                :aria-label="`查看任务 ${task.task_id} 详情`"
                @click="openTask(task.task_id, $event)"
                @keydown.enter="openTask(task.task_id, $event)"
                @keydown.space.prevent="openTask(task.task_id, $event)"
              >
                <td data-label="任务 / 时间">
                  <code>{{ task.task_id }}</code>
                  <span class="cell-caption">{{ formatTime(task.created_at) }}</span>
                </td>
                <td data-label="模型">
                  <strong>{{ task.model_alias || "尚未路由" }}</strong>
                  <span class="cell-caption">{{ task.provider || "—" }}</span>
                </td>
                <td data-label="任务结果">
                  <span class="status-badge" :data-tone="taskTone(task.status)">
                    <i aria-hidden="true"></i>{{ taskStatusLabel(task.status) }}
                  </span>
                </td>
                <td data-label="调用事实">
                  <span class="status-badge" :data-tone="dispatchTone(task.dispatch_state)">
                    <i aria-hidden="true"></i>{{ dispatchLabel(task.dispatch_state) }}
                  </span>
                  <span class="cell-caption">{{ task.call_count }} 次尝试</span>
                </td>
                <td class="numeric-cell" data-label="Token">
                  <template v-if="task.call_count === 0">—</template>
                  <template v-else>
                    {{ formatNumber((task.input_tokens ?? 0) + (task.output_tokens ?? 0)) }}
                    <span v-if="task.usage_unknown_calls" class="cell-caption cell-caption--warning">
                      {{ task.usage_unknown_calls }} 次用量未上报
                    </span>
                    <span v-else class="cell-caption">
                      缓存 {{ formatNumber(task.cached_input_tokens) }}
                    </span>
                  </template>
                </td>
                <td class="row-action"><span class="row-arrow" aria-hidden="true">↗</span></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!loading && !tasks.length" class="empty-state">
            <div class="empty-orbit" aria-hidden="true"><span></span></div>
            <strong>没有匹配的任务</strong>
            <p>清除筛选，或运行一条新的 LingShu 任务。</p>
            <button type="button" @click="clearFilters">清除筛选</button>
          </div>
        </div>
      </section>
      </template>

      <ProviderAnalyticsView
        v-else-if="activeView !== 'tokens'"
        :key="activeView"
        :provider-key="activeView"
        :display-name="currentPage.title"
        :refresh-version="refreshVersion"
      />
      <TokenOverviewView v-else :refresh-version="refreshVersion" />
      </main>
    </div>

    <div v-if="detailLoading" class="detail-loading" role="status">正在读取任务轨迹…</div>

    <div v-if="selectedTask" class="drawer-layer" @click.self="closeTask">
      <aside ref="taskDrawer" class="task-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <header class="drawer-header">
          <div>
            <p class="section-kicker">TASK TRACE</p>
            <h2 id="drawer-title">任务详情</h2>
          </div>
          <button ref="closeButton" class="icon-button" type="button" aria-label="关闭详情" @click="closeTask">×</button>
        </header>

        <section class="task-identity">
          <code>{{ selectedTask.task_id }}</code>
          <p>{{ selectedTask.prompt_preview || "没有提示词摘要" }}</p>
          <div class="badge-row">
            <span class="status-badge" :data-tone="taskTone(selectedTask.status)">
              <i aria-hidden="true"></i>{{ taskStatusLabel(selectedTask.status) }}
            </span>
            <span class="status-badge" :data-tone="dispatchTone(selectedTask.dispatch_state)">
              <i aria-hidden="true"></i>{{ dispatchLabel(selectedTask.dispatch_state) }}
            </span>
          </div>
        </section>

        <dl class="metadata-grid">
          <div><dt>模型</dt><dd>{{ selectedTask.model_alias || "—" }}</dd></div>
          <div><dt>Provider</dt><dd>{{ selectedTask.provider || "—" }}</dd></div>
          <div><dt>开始</dt><dd>{{ formatTime(selectedTask.started_at) }}</dd></div>
          <div><dt>结束</dt><dd>{{ formatTime(selectedTask.finished_at) }}</dd></div>
          <div><dt>路由规则</dt><dd>{{ selectedTask.route_rule || "—" }}</dd></div>
          <div><dt>失败阶段</dt><dd>{{ selectedTask.failure_phase || "—" }}</dd></div>
        </dl>

        <div v-if="selectedTask.error_preview" class="task-error">
          <span>任务错误</span>
          <p>{{ selectedTask.error_preview }}</p>
        </div>

        <section class="call-section">
          <div class="call-heading">
            <h3>模型调用</h3>
            <span>{{ selectedTask.calls.length }} 条记录</span>
          </div>
          <ol v-if="selectedTask.calls.length" class="call-timeline" aria-label="模型调用时间线">
            <li v-for="call in selectedTask.calls" :key="call.call_id">
              <span class="timeline-node" :data-tone="callTone(call.display_state)" aria-hidden="true"></span>
              <article>
                <div class="call-title">
                  <div><span>第 {{ call.call_seq }} 次</span><strong>{{ call.model }}</strong></div>
                  <span class="status-badge" :data-tone="callTone(call.display_state)">
                    {{ callStateLabel(call.display_state) }}
                  </span>
                </div>
                <dl>
                  <div><dt>耗时</dt><dd>{{ formatDuration(call.duration_ms) }}</dd></div>
                  <div><dt>输入</dt><dd>{{ call.usage_reported ? formatNumber(call.input_tokens) : "未知" }}</dd></div>
                  <div><dt>缓存</dt><dd>{{ call.usage_reported ? formatNumber(call.cached_input_tokens) : "未知" }}</dd></div>
                  <div><dt>输出</dt><dd>{{ call.usage_reported ? formatNumber(call.output_tokens) : "未知" }}</dd></div>
                </dl>
                <p v-if="call.error_preview" class="call-error">{{ call.error_preview }}</p>
              </article>
            </li>
          </ol>
          <div v-else class="no-calls">没有模型调用记录，任务在派发前结束。</div>
        </section>
      </aside>
    </div>
  </div>
</template>
