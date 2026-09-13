from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from lingshu.observability.redaction import redact_preview
from lingshu.settings import ProviderConfig

_RESPONDED_STATES = {"SUCCEEDED", "HTTP_ERROR", "INVALID_RESPONSE"}
_UNKNOWN_STATES = {"FAILED", "TIMED_OUT", "NETWORK_ERROR", "CANCELLED"}


class DashboardQueries:
    """通过只读 SQLite 连接提供 Dashboard 查询。"""

    def __init__(self, path: Path, stale_after_seconds: float = 240) -> None:
        self.path = path.resolve()
        self.stale_after_seconds = stale_after_seconds

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def overview(self) -> dict[str, Any]:
        with self._connect() as connection:
            tasks = dict(
                connection.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status = 'ACCEPTED' THEN 1 ELSE 0 END) AS accepted,
                           SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                           SUM(CASE WHEN status NOT IN ('ACCEPTED', 'FAILED') THEN 1 ELSE 0 END)
                               AS active
                    FROM tasks
                    """
                ).fetchone()
            )
            calls = dict(
                connection.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN state = 'SUCCEEDED' THEN 1 ELSE 0 END) AS successful,
                           SUM(CASE WHEN state IN ('SUCCEEDED', 'HTTP_ERROR', 'INVALID_RESPONSE')
                               THEN 1 ELSE 0 END) AS responded,
                           SUM(CASE WHEN state IN ('FAILED', 'HTTP_ERROR', 'INVALID_RESPONSE')
                               THEN 1 ELSE 0 END) AS failed,
                           SUM(CASE WHEN state IN ('TIMED_OUT', 'NETWORK_ERROR', 'CANCELLED')
                               THEN 1 ELSE 0 END) AS outcome_unknown,
                           SUM(CASE WHEN state = 'ATTEMPTING' THEN 1 ELSE 0 END) AS attempting,
                           SUM(input_tokens) AS input_tokens,
                           SUM(cached_input_tokens) AS cached_input_tokens,
                           SUM(output_tokens) AS output_tokens,
                           SUM(CASE WHEN usage_reported = 0 THEN 1 ELSE 0 END)
                               AS usage_unknown_calls,
                           SUM(CASE WHEN pricing_mode = 'METERED' AND usage_reported = 1
                               THEN estimated_cost_cny ELSE 0 END) AS metered_cost_cny,
                           SUM(CASE WHEN pricing_mode = 'SUBSCRIPTION' THEN 1 ELSE 0 END)
                               AS subscription_calls,
                           SUM(CASE WHEN pricing_mode = 'UNKNOWN' THEN 1 ELSE 0 END)
                               AS pricing_unknown_calls
                    FROM calls WHERE source = 'TASK'
                    """
                ).fetchone()
            )
            latest = connection.execute(
                """
                SELECT * FROM calls WHERE source = 'TASK'
                ORDER BY created_at DESC, call_id DESC LIMIT 1
                """
            ).fetchone()
        stale = self._count_stale_attempts()
        attempting = max(0, int(calls.get("attempting") or 0) - stale)
        input_tokens = int(calls.get("input_tokens") or 0)
        cached_tokens = int(calls.get("cached_input_tokens") or 0)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tasks": {key: int(value or 0) for key, value in tasks.items()},
            "calls": {
                "total": int(calls.get("total") or 0),
                "successful": int(calls.get("successful") or 0),
                "responded": int(calls.get("responded") or 0),
                "failed": int(calls.get("failed") or 0),
                "outcome_unknown": int(calls.get("outcome_unknown") or 0) + stale,
                "attempting": attempting,
                "stale": stale,
            },
            "tokens": {
                "input": input_tokens,
                "cached_input": cached_tokens,
                "non_cached_input": max(0, input_tokens - cached_tokens),
                "output": int(calls.get("output_tokens") or 0),
                "unknown_calls": int(calls.get("usage_unknown_calls") or 0),
            },
            "cost": {
                "metered_cny": round(float(calls.get("metered_cost_cny") or 0), 6),
                "subscription_calls": int(calls.get("subscription_calls") or 0),
                "unknown_calls": int(calls.get("pricing_unknown_calls") or 0),
            },
            "latest_call": self._serialize_call(latest) if latest else None,
        }

    def list_tasks(
        self,
        *,
        status: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        search: str | None = None,
        dispatch: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        stale_threshold = (
            datetime.now(UTC) - timedelta(seconds=self.stale_after_seconds)
        ).isoformat()
        parameters: list[Any] = [stale_threshold]
        if status:
            clauses.append("t.status = ?")
            parameters.append(status)
        if provider:
            clauses.append("t.provider = ?")
            parameters.append(provider)
        if model:
            clauses.append("t.model_alias = ?")
            parameters.append(model)
        if search:
            clauses.append("(t.task_id LIKE ? OR t.model_alias LIKE ?)")
            pattern = f"%{search}%"
            parameters.extend((pattern, pattern))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        dispatch_where = ""
        if dispatch:
            dispatch_where = "WHERE computed_dispatch_state = ?"
            parameters.append(dispatch)
        parameters.append(limit)
        sql = f"""
            WITH task_summary AS (
            SELECT t.*,
                   COUNT(c.call_id) AS call_count,
                   SUM(CASE WHEN c.state IN ('SUCCEEDED', 'HTTP_ERROR', 'INVALID_RESPONSE')
                       THEN 1 ELSE 0 END) AS responded_calls,
                   SUM(CASE WHEN c.state IN ('TIMED_OUT', 'NETWORK_ERROR', 'CANCELLED', 'FAILED')
                       THEN 1 ELSE 0 END) AS unknown_calls,
                   SUM(CASE WHEN c.state = 'ATTEMPTING' THEN 1 ELSE 0 END) AS attempting_calls,
                   SUM(CASE WHEN c.state = 'ATTEMPTING' AND c.started_at < ?
                       THEN 1 ELSE 0 END) AS stale_calls,
                   SUM(c.input_tokens) AS input_tokens,
                   SUM(c.cached_input_tokens) AS cached_input_tokens,
                   SUM(c.output_tokens) AS output_tokens,
                   SUM(CASE WHEN c.usage_reported = 0 THEN 1 ELSE 0 END)
                       AS usage_unknown_calls,
                   SUM(CASE WHEN c.pricing_mode = 'METERED' AND c.usage_reported = 1
                       THEN c.estimated_cost_cny ELSE 0 END) AS metered_cost_cny,
                   SUM(CASE WHEN c.pricing_mode = 'METERED' AND c.usage_reported = 1
                       THEN 1 ELSE 0 END) AS metered_usage_calls,
                   SUM(CASE WHEN c.pricing_mode = 'SUBSCRIPTION' THEN 1 ELSE 0 END)
                       AS subscription_calls
            FROM tasks t
            LEFT JOIN calls c ON c.task_id = t.task_id AND c.source = 'TASK'
            {where}
            GROUP BY t.task_id
            ), classified AS (
            SELECT *,
                   CASE
                       WHEN call_count = 0 THEN 'NOT_DISPATCHED'
                       WHEN responded_calls > 0 THEN 'RESPONDED'
                       WHEN attempting_calls - stale_calls > 0 THEN 'ATTEMPTING'
                       ELSE 'OUTCOME_UNKNOWN'
                   END AS computed_dispatch_state
            FROM task_summary
            )
            SELECT * FROM classified
            {dispatch_where}
            ORDER BY created_at DESC, task_id DESC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._serialize_task(row) for row in rows]

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                return None
            calls = connection.execute(
                """
                SELECT * FROM calls WHERE task_id = ? AND source = 'TASK'
                ORDER BY call_seq ASC, created_at ASC
                """,
                (task_id,),
            ).fetchall()
        serialized_calls = [self._serialize_call(row) for row in calls]
        result = self._serialize_task(task, serialized_calls)
        result["calls"] = serialized_calls
        return result

    def list_calls(
        self,
        *,
        source: str = "TASK",
        state: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["source = ?"]
        parameters: list[Any] = [source]
        for column, value in (("state", state), ("provider", provider), ("model", model)):
            if value:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        parameters.append(limit)
        sql = f"""
            SELECT * FROM calls WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, call_id DESC LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._serialize_call(row) for row in rows]

    def daily_analytics(
        self,
        providers: dict[str, ProviderConfig],
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        provider: str | None = None,
        model: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """按北京时间和筛选条件聚合连续自然日的模型调用事实。"""
        shanghai_timezone = timezone(timedelta(hours=8), "Asia/Shanghai")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        local_today = current.astimezone(shanghai_timezone).date()
        range_end = end_date or local_today
        range_start = start_date or (range_end - timedelta(days=days - 1))
        buckets: list[dict[str, Any]] = []
        local_date = range_start
        while local_date <= range_end:
            offset = (local_today - local_date).days
            label = {0: "今天", 1: "昨天", 2: "前天"}.get(
                offset, f"{local_date.month}/{local_date.day}"
            )
            buckets.append(
                {
                    "date": local_date.isoformat(),
                    "label": label,
                }
            )
            local_date += timedelta(days=1)

        selected_providers = (
            {provider: providers[provider]} if provider is not None else providers
        )
        provider_items = self._analytics_provider_skeleton(selected_providers, buckets)
        stale_before = (current.astimezone(UTC) - timedelta(seconds=self.stale_after_seconds))
        utc_start = datetime.combine(
            range_start, time.min, shanghai_timezone
        ).astimezone(UTC)
        utc_end = datetime.combine(
            range_end + timedelta(days=1), time.min, shanghai_timezone
        ).astimezone(UTC)
        clauses = ["c.source = 'TASK'", "c.created_at >= ?", "c.created_at < ?"]
        parameters: list[Any] = [
            stale_before.isoformat(),
            stale_before.isoformat(),
            utc_start.isoformat(),
            utc_end.isoformat(),
        ]
        if provider is not None:
            clauses.append("c.provider = ?")
            parameters.append(provider)
        if model is not None:
            clauses.append("c.model = ?")
            parameters.append(model)
        where = " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                    SELECT date(c.created_at, '+8 hours') AS bucket_date,
                           c.provider, c.model,
                           CASE
                               WHEN SUM(CASE WHEN c.pricing_mode = 'SUBSCRIPTION'
                                   THEN 1 ELSE 0 END) > 0
                                   AND SUM(CASE WHEN c.pricing_mode = 'METERED'
                                   THEN 1 ELSE 0 END) > 0 THEN 'MIXED'
                               WHEN SUM(CASE WHEN c.pricing_mode = 'SUBSCRIPTION'
                                   THEN 1 ELSE 0 END) > 0 THEN 'SUBSCRIPTION'
                               WHEN SUM(CASE WHEN c.pricing_mode = 'METERED'
                                   THEN 1 ELSE 0 END) > 0 THEN 'METERED'
                               ELSE 'UNKNOWN'
                           END AS pricing_mode,
                           GROUP_CONCAT(DISTINCT COALESCE(
                               NULLIF(c.model_alias, ''), NULLIF(t.model_alias, ''), ''
                           )) AS aliases,
                           COUNT(*) AS attempts,
                           SUM(CASE WHEN c.state IN
                               ('SUCCEEDED', 'HTTP_ERROR', 'INVALID_RESPONSE')
                               THEN 1 ELSE 0 END) AS responded,
                           SUM(CASE WHEN c.state = 'SUCCEEDED' THEN 1 ELSE 0 END)
                               AS succeeded,
                           SUM(CASE WHEN c.state = 'ATTEMPTING' AND c.started_at >= ?
                               THEN 1 ELSE 0 END) AS attempting,
                           SUM(CASE WHEN c.state IN
                               ('FAILED', 'TIMED_OUT', 'NETWORK_ERROR', 'CANCELLED')
                               OR (c.state = 'ATTEMPTING' AND c.started_at < ?)
                               THEN 1 ELSE 0 END) AS outcome_unknown,
                           SUM(CASE WHEN c.usage_reported = 1 THEN 1 ELSE 0 END)
                               AS usage_known_calls,
                           SUM(CASE WHEN c.usage_reported = 0 THEN 1 ELSE 0 END)
                               AS usage_unknown_calls,
                           SUM(CASE WHEN c.usage_reported = 1 THEN c.input_tokens ELSE 0 END)
                               AS input_tokens,
                           SUM(CASE WHEN c.usage_reported = 1
                               THEN c.cached_input_tokens ELSE 0 END) AS cached_input_tokens,
                           SUM(CASE WHEN c.usage_reported = 1 THEN c.output_tokens ELSE 0 END)
                               AS output_tokens,
                           SUM(CASE WHEN c.pricing_mode = 'SUBSCRIPTION' THEN 1 ELSE 0 END)
                               AS subscription_attempts
                    FROM calls c
                    LEFT JOIN tasks t ON t.task_id = c.task_id
                    WHERE {where}
                    GROUP BY bucket_date, c.provider, c.model
                    ORDER BY bucket_date ASC, attempts DESC, c.model ASC
                """,
                parameters,
            ).fetchall()
            for row in rows:
                self._merge_analytics_row(
                    provider_items,
                    selected_providers,
                    row["bucket_date"],
                    row,
                    buckets,
                )

        self._complete_configured_models(provider_items, selected_providers, buckets)
        public_buckets = [
            {"date": bucket["date"], "label": bucket["label"]} for bucket in buckets
        ]
        result_providers = list(provider_items.values())
        totals = self._empty_analytics_metrics()
        for provider_item in result_providers:
            provider_item["models"] = sorted(
                provider_item["models"].values(),
                key=lambda item: (-item["totals"]["attempts"], item["model"]),
            )
            self._add_analytics_metrics(totals, provider_item["totals"])
        return {
            "generated_at": current.astimezone(UTC).isoformat(),
            "timezone": "Asia/Shanghai",
            "range": {
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "days": len(buckets),
            },
            "days": public_buckets,
            "totals": totals,
            "providers": result_providers,
        }

    @classmethod
    def _analytics_provider_skeleton(
        cls,
        providers: dict[str, ProviderConfig],
        buckets: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "provider": name,
                "display_name": provider.display_name,
                "configured": provider.api_key is not None,
                "totals": cls._empty_analytics_metrics(),
                "days": [
                    {"date": bucket["date"], **cls._empty_analytics_metrics()}
                    for bucket in buckets
                ],
                "models": {},
            }
            for name, provider in providers.items()
        }

    @classmethod
    def _merge_analytics_row(
        cls,
        provider_items: dict[str, dict[str, Any]],
        providers: dict[str, ProviderConfig],
        bucket_date: str,
        row: sqlite3.Row,
        buckets: list[dict[str, Any]],
    ) -> None:
        provider_name = row["provider"]
        if provider_name not in provider_items:
            provider_items[provider_name] = {
                "provider": provider_name,
                "display_name": provider_name,
                "configured": False,
                "totals": cls._empty_analytics_metrics(),
                "days": [
                    {"date": bucket["date"], **cls._empty_analytics_metrics()}
                    for bucket in buckets
                ],
                "models": {},
            }
        provider_item = provider_items[provider_name]
        aliases = sorted(filter(None, (row["aliases"] or "").split(",")))
        if not aliases and provider_name in providers:
            aliases = sorted(
                alias
                for alias, model in providers[provider_name].models.items()
                if model.id == row["model"]
            )
        model_key = row["model"]
        pricing_mode = row["pricing_mode"]
        model_item = provider_item["models"].setdefault(
            model_key,
            {
                "key": model_key,
                "model": row["model"],
                "aliases": aliases,
                "pricing_mode": pricing_mode,
                "totals": cls._empty_analytics_metrics(),
                "days": [
                    {"date": bucket["date"], **cls._empty_analytics_metrics()}
                    for bucket in buckets
                ],
            },
        )
        if model_item["pricing_mode"] != pricing_mode:
            model_item["pricing_mode"] = "MIXED"
        model_item["aliases"] = sorted(set(model_item["aliases"]) | set(aliases))
        metrics = cls._analytics_metrics(row)
        model_day = next(item for item in model_item["days"] if item["date"] == bucket_date)
        provider_day = next(
            item for item in provider_item["days"] if item["date"] == bucket_date
        )
        cls._add_analytics_metrics(model_day, metrics)
        cls._add_analytics_metrics(model_item["totals"], metrics)
        cls._add_analytics_metrics(provider_day, metrics)
        cls._add_analytics_metrics(provider_item["totals"], metrics)

    @classmethod
    def _complete_configured_models(
        cls,
        provider_items: dict[str, dict[str, Any]],
        providers: dict[str, ProviderConfig],
        buckets: list[dict[str, Any]],
    ) -> None:
        for provider_name, config in providers.items():
            provider_item = provider_items[provider_name]
            observed_aliases = {
                alias
                for item in provider_item["models"].values()
                for alias in item["aliases"]
            }
            for alias, model in config.models.items():
                if alias in observed_aliases:
                    continue
                key = model.id
                existing = provider_item["models"].get(key)
                if existing is not None:
                    existing["aliases"] = sorted(set(existing["aliases"]) | {alias})
                    continue
                provider_item["models"][key] = {
                    "key": key,
                    "model": model.id,
                    "aliases": [alias],
                    "pricing_mode": model.pricing_mode,
                    "totals": cls._empty_analytics_metrics(),
                    "days": [
                        {"date": bucket["date"], **cls._empty_analytics_metrics()}
                        for bucket in buckets
                    ],
                }

    @staticmethod
    def _empty_analytics_metrics() -> dict[str, int]:
        return {
            "attempts": 0,
            "responded": 0,
            "succeeded": 0,
            "attempting": 0,
            "outcome_unknown": 0,
            "usage_known_calls": 0,
            "usage_unknown_calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "non_cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "subscription_attempts": 0,
        }

    @classmethod
    def _analytics_metrics(cls, row: sqlite3.Row) -> dict[str, int]:
        metrics = cls._empty_analytics_metrics()
        for key in metrics:
            if key not in {"non_cached_input_tokens", "total_tokens"}:
                metrics[key] = int(row[key] or 0)
        metrics["non_cached_input_tokens"] = max(
            0, metrics["input_tokens"] - metrics["cached_input_tokens"]
        )
        metrics["total_tokens"] = metrics["input_tokens"] + metrics["output_tokens"]
        return metrics

    @staticmethod
    def _add_analytics_metrics(target: dict[str, Any], source: dict[str, int]) -> None:
        for key, value in source.items():
            target[key] += value

    def _count_stale_attempts(self) -> int:
        threshold = (datetime.now(UTC) - timedelta(seconds=self.stale_after_seconds)).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM calls
                WHERE source = 'TASK' AND state = 'ATTEMPTING' AND started_at < ?
                """,
                (threshold,),
            ).fetchone()
        return int(row[0])

    def _serialize_task(
        self, row: sqlite3.Row, calls: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        item = dict(row)
        item.pop("computed_dispatch_state", None)
        item["prompt_preview"] = redact_preview(item.pop("prompt", None))
        item["error_preview"] = redact_preview(item.pop("error", None))
        item.pop("workspace", None)
        item.pop("result_path", None)
        call_items = calls or []
        call_count = int(item.get("call_count") or len(call_items))
        responded = int(item.get("responded_calls") or 0)
        unknown = int(item.get("unknown_calls") or 0)
        attempting = int(item.get("attempting_calls") or 0)
        stale = int(item.get("stale_calls") or 0)
        attempting = max(0, attempting - stale)
        unknown += stale
        if call_items:
            responded = sum(call["state"] in _RESPONDED_STATES for call in call_items)
            unknown = sum(
                call["state"] in _UNKNOWN_STATES or call["display_state"] == "STALE"
                for call in call_items
            )
            attempting = sum(call["display_state"] == "ATTEMPTING" for call in call_items)
        if call_count == 0:
            dispatch_state = "NOT_DISPATCHED"
        elif responded:
            dispatch_state = "RESPONDED"
        elif attempting:
            dispatch_state = "ATTEMPTING"
        elif unknown:
            dispatch_state = "OUTCOME_UNKNOWN"
        else:
            dispatch_state = "OUTCOME_UNKNOWN"
        item["call_count"] = call_count
        item["dispatch_state"] = dispatch_state
        result_path = row["result_path"] if "result_path" in row.keys() else None
        item["result_available"] = bool(result_path)
        return item

    def _serialize_call(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["display_state"] = self._display_state(item["state"], item["started_at"])
        item["error_preview"] = redact_preview(item.pop("error", None))
        item["estimated_cost_cny"] = (
            item["estimated_cost_cny"]
            if item["pricing_mode"] == "METERED" and item["usage_reported"]
            else None
        )
        for key in (
            "pricing_currency",
            "input_price_per_million",
            "cached_input_price_per_million",
            "output_price_per_million",
            "usd_cny_rate",
            "pricing_config_version",
            "correlation_id",
            "ok",
            "latency_ms",
            "created_at",
        ):
            item.pop(key, None)
        return item

    def _display_state(self, state: str, started_at: str) -> str:
        if state != "ATTEMPTING":
            return state
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return "STALE"
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if datetime.now(UTC) - started > timedelta(seconds=self.stale_after_seconds):
            return "STALE"
        return "ATTEMPTING"
