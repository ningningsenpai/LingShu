export interface Overview {
  generated_at: string;
  tasks: {
    total: number;
    accepted: number;
    failed: number;
    active: number;
  };
  calls: {
    total: number;
    successful: number;
    responded: number;
    failed: number;
    outcome_unknown: number;
    attempting: number;
    stale: number;
  };
  tokens: {
    input: number;
    cached_input: number;
    non_cached_input: number;
    output: number;
    unknown_calls: number;
  };
  cost: {
    metered_cny: number;
    subscription_calls: number;
    unknown_calls: number;
  };
}

export interface CallDetail {
  call_id: string;
  task_id: string | null;
  provider: string;
  model: string;
  model_alias: string | null;
  state: string;
  display_state: string;
  source: string;
  call_seq: number;
  request_id: string | null;
  finish_reason: string | null;
  error_type: string | null;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  usage_reported: number;
  duration_ms: number | null;
  estimated_cost_cny: number | null;
  pricing_mode: string;
  error_preview: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface TaskSummary {
  task_id: string;
  status: string;
  provider: string | null;
  model_alias: string | null;
  risk: string;
  route_rule: string | null;
  failure_phase: string | null;
  started_at: string;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  prompt_preview: string | null;
  error_preview: string | null;
  call_count: number;
  dispatch_state: string;
  input_tokens?: number;
  cached_input_tokens?: number;
  output_tokens?: number;
  usage_unknown_calls?: number;
  metered_cost_cny?: number;
  metered_usage_calls?: number;
  subscription_calls?: number;
  result_available: boolean;
}

export interface TaskDetail extends TaskSummary {
  calls: CallDetail[];
}

export interface AnalyticsMetrics {
  attempts: number;
  responded: number;
  succeeded: number;
  attempting: number;
  outcome_unknown: number;
  usage_known_calls: number;
  usage_unknown_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  non_cached_input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  subscription_attempts: number;
}

export interface AnalyticsDay extends AnalyticsMetrics {
  date: string;
}

export interface AnalyticsModel {
  key: string;
  model: string;
  aliases: string[];
  pricing_mode: string;
  totals: AnalyticsMetrics;
  days: AnalyticsDay[];
}

export interface AnalyticsProvider {
  provider: string;
  display_name: string;
  configured: boolean;
  totals: AnalyticsMetrics;
  days: AnalyticsDay[];
  models: AnalyticsModel[];
}

export interface DailyAnalytics {
  generated_at: string;
  timezone: string;
  range: {
    start: string;
    end: string;
    days: number;
  };
  days: Array<{
    date: string;
    label: string;
  }>;
  totals: AnalyticsMetrics;
  providers: AnalyticsProvider[];
}
