const numberFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const currencyFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

export function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(value ?? 0);
}

export function formatCurrency(value: number | null | undefined): string {
  return currencyFormatter.format(value ?? 0);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDuration(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

export function taskStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    RECEIVED: "已接收",
    DISPATCHED: "执行中",
    ACCEPTED: "已完成",
    FAILED: "失败",
    NEEDS_USER_INPUT: "等待输入",
  };
  return labels[status] ?? status;
}

export function dispatchLabel(status: string): string {
  const labels: Record<string, string> = {
    NOT_DISPATCHED: "未派发",
    ATTEMPTING: "派发中",
    RESPONDED: "确认响应",
    OUTCOME_UNKNOWN: "结果未知",
  };
  return labels[status] ?? status;
}

export function callStateLabel(status: string): string {
  const labels: Record<string, string> = {
    ATTEMPTING: "派发中",
    STALE: "可能中断",
    SUCCEEDED: "响应成功",
    HTTP_ERROR: "HTTP 错误",
    INVALID_RESPONSE: "响应无效",
    TIMED_OUT: "请求超时",
    NETWORK_ERROR: "网络错误",
    CANCELLED: "已取消",
    FAILED: "调用失败",
  };
  return labels[status] ?? status;
}
