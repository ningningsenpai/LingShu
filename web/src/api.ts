import type { DailyAnalytics, Overview, TaskDetail, TaskSummary } from "./types";

interface TaskListResponse {
  items: TaskSummary[];
  count: number;
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new Error(payload?.error?.message ?? `请求失败（${response.status}）`);
  }
  return (await response.json()) as T;
}

export function fetchOverview(): Promise<Overview> {
  return request<Overview>("/api/v1/overview");
}

export function fetchTasks(parameters: URLSearchParams): Promise<TaskListResponse> {
  return request<TaskListResponse>(`/api/v1/tasks?${parameters.toString()}`);
}

export function fetchTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/v1/tasks/${encodeURIComponent(taskId)}`);
}

export function fetchDailyAnalytics(
  parameters = new URLSearchParams(),
): Promise<DailyAnalytics> {
  const query = parameters.toString();
  return request<DailyAnalytics>(`/api/v1/analytics/daily${query ? `?${query}` : ""}`);
}
