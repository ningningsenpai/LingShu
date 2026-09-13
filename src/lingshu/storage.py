from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from lingshu.errors import BudgetExceededError, StorageError
from lingshu.schemas import CallSource, ModelResponse, TaskRecord, TaskStatus
from lingshu.settings import ModelConfig


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    """持久化任务、调用记录和预算预留。"""

    _SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._is_legacy_database():
            self._backup_legacy_database()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _is_legacy_database(self) -> bool:
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return False
        with sqlite3.connect(self.path) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'"
            ).fetchone()
            if table is None:
                return False
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(calls)").fetchall()
            }
        return "state" not in columns

    def _backup_legacy_database(self) -> None:
        target = self.path.with_name(f"{self.path.stem}.pre-dashboard-v1.bak")
        if target.exists():
            return
        with sqlite3.connect(self.path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            calls_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'"
            ).fetchone()
            if calls_exists is None:
                self._create_latest_schema(connection)
            else:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(calls)").fetchall()
                }
                if "state" not in columns:
                    self._migrate_legacy_schema(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (self._SCHEMA_VERSION, _now()),
            )
            self._create_indexes(connection)

    @staticmethod
    def _create_latest_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                prompt TEXT NOT NULL,
                provider TEXT,
                model_alias TEXT,
                workspace TEXT NOT NULL,
                result_path TEXT,
                error TEXT,
                risk TEXT NOT NULL DEFAULT 'normal',
                route_rule TEXT,
                failure_phase TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calls (
                call_id TEXT PRIMARY KEY,
                task_id TEXT,
                correlation_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_alias TEXT,
                state TEXT NOT NULL,
                source TEXT NOT NULL,
                call_seq INTEGER NOT NULL,
                request_id TEXT,
                finish_reason TEXT,
                error_type TEXT,
                input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                usage_reported INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                duration_ms INTEGER,
                estimated_cost_cny REAL NOT NULL,
                pricing_mode TEXT NOT NULL,
                pricing_currency TEXT,
                input_price_per_million REAL,
                cached_input_price_per_million REAL,
                output_price_per_million REAL,
                usd_cny_rate REAL,
                pricing_config_version TEXT,
                ok INTEGER NOT NULL,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS budget_events (
                reservation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                amount_cny REAL NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _migrate_legacy_schema(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            ALTER TABLE tasks RENAME TO tasks_legacy;
            ALTER TABLE calls RENAME TO calls_legacy;

            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                prompt TEXT NOT NULL,
                provider TEXT,
                model_alias TEXT,
                workspace TEXT NOT NULL,
                result_path TEXT,
                error TEXT,
                risk TEXT NOT NULL DEFAULT 'normal',
                route_rule TEXT,
                failure_phase TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO tasks (
                task_id, status, prompt, provider, model_alias, workspace, result_path,
                error, risk, route_rule, failure_phase, started_at, finished_at,
                created_at, updated_at
            )
            SELECT
                task_id, status, prompt, provider, model_alias, workspace, result_path,
                error, 'normal', NULL, NULL, created_at,
                CASE WHEN status IN ('ACCEPTED', 'FAILED') THEN updated_at ELSE NULL END,
                created_at, updated_at
            FROM tasks_legacy;

            CREATE TABLE calls (
                call_id TEXT PRIMARY KEY,
                task_id TEXT,
                correlation_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_alias TEXT,
                state TEXT NOT NULL,
                source TEXT NOT NULL,
                call_seq INTEGER NOT NULL,
                request_id TEXT,
                finish_reason TEXT,
                error_type TEXT,
                input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                usage_reported INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                duration_ms INTEGER,
                estimated_cost_cny REAL NOT NULL,
                pricing_mode TEXT NOT NULL,
                pricing_currency TEXT,
                input_price_per_million REAL,
                cached_input_price_per_million REAL,
                output_price_per_million REAL,
                usd_cny_rate REAL,
                pricing_config_version TEXT,
                ok INTEGER NOT NULL,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO calls (
                call_id, task_id, correlation_id, provider, model, model_alias,
                state, source, call_seq, request_id, finish_reason, error_type,
                input_tokens, cached_input_tokens, output_tokens, usage_reported,
                latency_ms, duration_ms, estimated_cost_cny, pricing_mode,
                pricing_currency, input_price_per_million,
                cached_input_price_per_million, output_price_per_million,
                usd_cny_rate, pricing_config_version, ok, error,
                started_at, finished_at, created_at
            )
            SELECT
                call_id,
                CASE WHEN task_id LIKE 'doctor-%' THEN NULL ELSE task_id END,
                task_id,
                provider,
                model,
                NULL,
                CASE WHEN ok = 1 THEN 'SUCCEEDED' ELSE 'NETWORK_ERROR' END,
                CASE WHEN task_id LIKE 'doctor-%' THEN 'DOCTOR' ELSE 'TASK' END,
                ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY created_at, call_id),
                NULL,
                NULL,
                CASE WHEN ok = 1 THEN NULL ELSE 'LEGACY_ERROR' END,
                input_tokens,
                cached_input_tokens,
                output_tokens,
                CASE
                    WHEN input_tokens + cached_input_tokens + output_tokens > 0 THEN 1
                    ELSE 0
                END,
                latency_ms,
                CASE WHEN latency_ms > 0 THEN latency_ms ELSE NULL END,
                estimated_cost_cny,
                CASE
                    WHEN provider = 'ark_coding' THEN 'SUBSCRIPTION'
                    WHEN estimated_cost_cny > 0 THEN 'METERED'
                    ELSE 'UNKNOWN'
                END,
                NULL, NULL, NULL, NULL, NULL, NULL,
                ok,
                error,
                created_at,
                created_at,
                created_at
            FROM calls_legacy;

            DROP TABLE tasks_legacy;
            DROP TABLE calls_legacy;
            """
        )
        connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _create_indexes(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_status_created
                ON tasks(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tasks_created
                ON tasks(created_at DESC, task_id DESC);
            CREATE INDEX IF NOT EXISTS idx_calls_task_seq
                ON calls(task_id, call_seq);
            CREATE INDEX IF NOT EXISTS idx_calls_provider_created
                ON calls(provider, model, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_calls_source_created
                ON calls(source, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_calls_created
                ON calls(created_at DESC, call_id DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_task_unique_seq
                ON calls(task_id, call_seq)
                WHERE task_id IS NOT NULL AND source = 'TASK';
            """
        )

    def reserve_budget(
        self, task_id: str, provider: str, amount_cny: float, limit_cny: float | None
    ) -> str | None:
        self._validate_budget_values(amount_cny, limit_cny)
        if limit_cny is None:
            return None
        reservation_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._reserve_budget_in_transaction(
                connection, reservation_id, task_id, provider, amount_cny, limit_cny
            )
        return reservation_id

    def begin_call_and_reserve(
        self,
        *,
        task_id: str,
        source: CallSource,
        provider: str,
        model: str,
        model_alias: str,
        reservation_amount_cny: float,
        budget_limit_cny: float | None,
        model_config: ModelConfig,
        usd_cny_rate: float,
        pricing_config_version: str,
    ) -> tuple[str, str | None]:
        """在同一事务中创建调用尝试并完成可选预算预留。"""
        self._validate_budget_values(reservation_amount_cny, budget_limit_cny)
        call_id = uuid.uuid4().hex
        reservation_id = uuid.uuid4().hex if budget_limit_cny is not None else None
        persisted_task_id = task_id if source == CallSource.TASK else None
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if reservation_id is not None and budget_limit_cny is not None:
                self._reserve_budget_in_transaction(
                    connection,
                    reservation_id,
                    task_id,
                    provider,
                    reservation_amount_cny,
                    budget_limit_cny,
                )
            row = connection.execute(
                "SELECT COALESCE(MAX(call_seq), 0) + 1 FROM calls WHERE correlation_id = ?",
                (task_id,),
            ).fetchone()
            call_seq = int(row[0])
            connection.execute(
                """
                INSERT INTO calls (
                    call_id, task_id, correlation_id, provider, model, model_alias,
                    state, source, call_seq, request_id, finish_reason, error_type,
                    input_tokens, cached_input_tokens, output_tokens, usage_reported,
                    latency_ms, duration_ms, estimated_cost_cny, pricing_mode,
                    pricing_currency, input_price_per_million,
                    cached_input_price_per_million, output_price_per_million,
                    usd_cny_rate, pricing_config_version, ok, error,
                    started_at, finished_at, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'ATTEMPTING', ?, ?, NULL, NULL, NULL,
                    0, 0, 0, 0, 0, NULL, 0, ?, ?, ?, ?, ?, ?, ?, 0, NULL,
                    ?, NULL, ?
                )
                """,
                (
                    call_id,
                    persisted_task_id,
                    task_id,
                    provider,
                    model,
                    model_alias,
                    source.value,
                    call_seq,
                    model_config.pricing_mode,
                    model_config.currency if model_config.pricing_mode == "METERED" else None,
                    model_config.input_price_per_million,
                    model_config.cached_input_price_per_million,
                    model_config.output_price_per_million,
                    usd_cny_rate if model_config.currency == "USD" else None,
                    pricing_config_version,
                    now,
                    now,
                ),
            )
        return call_id, reservation_id

    @staticmethod
    def _validate_budget_values(amount_cny: float, limit_cny: float | None) -> None:
        if not isfinite(amount_cny) or amount_cny < 0:
            raise ValueError("预算预留金额必须是非负有限数字")
        if limit_cny is not None and (not isfinite(limit_cny) or limit_cny < 0):
            raise ValueError("预算上限必须是非负有限数字")

    @staticmethod
    def _reserve_budget_in_transaction(
        connection: sqlite3.Connection,
        reservation_id: str,
        task_id: str,
        provider: str,
        amount_cny: float,
        limit_cny: float,
    ) -> None:
        committed = connection.execute(
            """
            SELECT COALESCE(SUM(amount_cny), 0)
            FROM budget_events
            WHERE provider = ? AND state IN ('reserved', 'settled')
            """,
            (provider,),
        ).fetchone()[0]
        if committed + amount_cny > limit_cny:
            raise BudgetExceededError(
                f"{provider} 试验预算不足：已承诺 ¥{committed:.4f}，"
                f"本次最多需要 ¥{amount_cny:.4f}，上限 ¥{limit_cny:.2f}"
            )
        now = _now()
        connection.execute(
            """
            INSERT INTO budget_events
            (reservation_id, task_id, provider, amount_cny, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'reserved', ?, ?)
            """,
            (reservation_id, task_id, provider, amount_cny, now, now),
        )

    def settle_budget(self, reservation_id: str | None, actual_cny: float) -> None:
        if not isfinite(actual_cny) or actual_cny < 0:
            raise ValueError("预算结算金额必须是非负有限数字")
        if reservation_id is None:
            return
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE budget_events
                SET amount_cny = ?, state = 'settled', updated_at = ?
                WHERE reservation_id = ? AND state = 'reserved'
                """,
                (actual_cny, _now(), reservation_id),
            )
            if cursor.rowcount != 1:
                raise StorageError("找不到可结算的预算预留记录")

    def complete_call(
        self,
        *,
        call_id: str,
        reservation_id: str | None,
        response: ModelResponse,
        duration_ms: int,
    ) -> None:
        """在同一事务中结算预算并完成调用记录。"""
        actual_cny = response.estimated_cost_cny
        if not isfinite(actual_cny) or actual_cny < 0:
            raise ValueError("预算结算金额必须是非负有限数字")
        usage = response.usage
        usage_reported = response.usage_reported or (
            usage.input_tokens + usage.cached_input_tokens + usage.output_tokens > 0
        )
        with self._connect() as connection:
            if reservation_id is not None:
                cursor = connection.execute(
                    """
                    UPDATE budget_events
                    SET amount_cny = ?, state = 'settled', updated_at = ?
                    WHERE reservation_id = ? AND state = 'reserved'
                    """,
                    (actual_cny, _now(), reservation_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("找不到可结算的预算预留记录")
            cursor = connection.execute(
                """
                UPDATE calls SET
                    model = ?, state = 'SUCCEEDED', request_id = ?, finish_reason = ?,
                    input_tokens = ?, cached_input_tokens = ?, output_tokens = ?,
                    usage_reported = ?, latency_ms = ?, duration_ms = ?,
                    estimated_cost_cny = ?, ok = 1, error = NULL, error_type = NULL,
                    finished_at = ?
                WHERE call_id = ? AND state = 'ATTEMPTING'
                """,
                (
                    response.model,
                    response.request_id,
                    response.finish_reason,
                    usage.input_tokens,
                    usage.cached_input_tokens,
                    usage.output_tokens,
                    int(usage_reported),
                    response.latency_ms,
                    duration_ms,
                    actual_cny,
                    _now(),
                    call_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError("找不到待完成的模型调用记录")

    def fail_call(
        self,
        *,
        call_id: str,
        reservation_id: str | None,
        state: str,
        error_type: str,
        error: str,
        duration_ms: int,
    ) -> None:
        """在同一事务中释放预算并完成失败调用记录。"""
        with self._connect() as connection:
            if reservation_id is not None:
                cursor = connection.execute(
                    """
                    UPDATE budget_events SET state = 'released', updated_at = ?
                    WHERE reservation_id = ? AND state = 'reserved'
                    """,
                    (_now(), reservation_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("找不到可释放的预算预留记录")
            cursor = connection.execute(
                """
                UPDATE calls SET state = ?, error_type = ?, error = ?, duration_ms = ?,
                    finished_at = ?, ok = 0
                WHERE call_id = ? AND state = 'ATTEMPTING'
                """,
                (state, error_type, error, duration_ms, _now(), call_id),
            )
            if cursor.rowcount != 1:
                raise StorageError("找不到待完成的模型调用记录")

    def release_budget(self, reservation_id: str | None) -> None:
        if reservation_id is None:
            return
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE budget_events SET state = 'released', updated_at = ?
                WHERE reservation_id = ? AND state = 'reserved'
                """,
                (_now(), reservation_id),
            )
            if cursor.rowcount != 1:
                raise StorageError("找不到可释放的预算预留记录")

    def spent_cny(self, provider: str) -> float:
        with self._connect() as connection:
            value = connection.execute(
                """
                SELECT COALESCE(SUM(amount_cny), 0)
                FROM budget_events WHERE provider = ? AND state = 'settled'
                """,
                (provider,),
            ).fetchone()[0]
        return float(value)

    def create_task(self, task: TaskRecord) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, status, prompt, provider, model_alias, workspace,
                    result_path, error, risk, route_rule, failure_phase,
                    started_at, finished_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    task.task_id,
                    task.status.value,
                    task.prompt,
                    task.provider,
                    task.model_alias,
                    str(task.workspace),
                    str(task.result_path) if task.result_path else None,
                    task.error,
                    task.risk,
                    task.route_rule,
                    task.failure_phase,
                    now,
                    now,
                    now,
                ),
            )

    def update_task_route(
        self, task_id: str, provider: str, model_alias: str, route_rule: str
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET provider = ?, model_alias = ?, route_rule = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (provider, model_alias, route_rule, _now(), task_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"找不到要更新路由的任务：{task_id}")

    def update_task(
        self,
        task_id: str,
        status: TaskStatus,
        result_path: Path | None = None,
        error: str | None = None,
        failure_phase: str | None = None,
    ) -> None:
        finished_at = _now() if status in {TaskStatus.ACCEPTED, TaskStatus.FAILED} else None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET status = ?, result_path = ?, error = ?, failure_phase = ?,
                    finished_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    status.value,
                    str(result_path) if result_path else None,
                    error,
                    failure_phase,
                    finished_at,
                    _now(),
                    task_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"找不到要更新的任务：{task_id}")

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def settle_and_record_call(
        self,
        reservation_id: str | None,
        task_id: str,
        response: ModelResponse,
        provider: str,
        model: str,
    ) -> None:
        """兼容旧调用方：在同一事务中结算预算并记录成功调用。"""
        actual_cny = response.estimated_cost_cny
        if not isfinite(actual_cny) or actual_cny < 0:
            raise ValueError("预算结算金额必须是非负有限数字")
        with self._connect() as connection:
            if reservation_id is not None:
                cursor = connection.execute(
                    """
                    UPDATE budget_events
                    SET amount_cny = ?, state = 'settled', updated_at = ?
                    WHERE reservation_id = ? AND state = 'reserved'
                    """,
                    (actual_cny, _now(), reservation_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("找不到可结算的预算预留记录")
            self._insert_call(connection, task_id, response, provider, model)

    def record_call(
        self,
        task_id: str,
        response: ModelResponse | None,
        provider: str,
        model: str,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            self._insert_call(connection, task_id, response, provider, model, error)

    @staticmethod
    def _insert_call(
        connection: sqlite3.Connection,
        task_id: str,
        response: ModelResponse | None,
        provider: str,
        model: str,
        error: str | None = None,
    ) -> None:
        usage = response.usage if response else None
        usage_reported = bool(
            response
            and (
                response.usage_reported
                or (
                    usage is not None
                    and (
                        usage.input_tokens
                        or usage.cached_input_tokens
                        or usage.output_tokens
                    )
                )
            )
        )
        created_at = _now()
        row = connection.execute(
            "SELECT COALESCE(MAX(call_seq), 0) + 1 FROM calls WHERE correlation_id = ?",
            (task_id,),
        ).fetchone()
        call_seq = int(row[0])
        connection.execute(
            """
            INSERT INTO calls (
                call_id, task_id, correlation_id, provider, model, model_alias,
                state, source, call_seq, request_id, finish_reason, error_type,
                input_tokens, cached_input_tokens, output_tokens, usage_reported,
                latency_ms, duration_ms, estimated_cost_cny, pricing_mode,
                pricing_currency, input_price_per_million,
                cached_input_price_per_million, output_price_per_million,
                usd_cny_rate, pricing_config_version, ok, error,
                started_at, finished_at, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, NULL, ?, 'TASK', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?
            )
            """,
            (
                uuid.uuid4().hex,
                task_id,
                task_id,
                provider,
                model,
                "SUCCEEDED" if response else "NETWORK_ERROR",
                call_seq,
                response.request_id if response else None,
                response.finish_reason if response else None,
                None if response else "LEGACY_ERROR",
                usage.input_tokens if usage else 0,
                usage.cached_input_tokens if usage else 0,
                usage.output_tokens if usage else 0,
                int(usage_reported),
                response.latency_ms if response else 0,
                response.latency_ms if response and response.latency_ms > 0 else None,
                response.estimated_cost_cny if response else 0,
                1 if response else 0,
                error,
                created_at,
                created_at,
                created_at,
            ),
        )

    def usage_summary(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT provider,
                       COUNT(*) AS calls,
                       SUM(ok) AS successful_calls,
                       SUM(input_tokens) AS input_tokens,
                       SUM(cached_input_tokens) AS cached_input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(estimated_cost_cny) AS estimated_cost_cny
                FROM calls
                WHERE source = 'TASK'
                GROUP BY provider ORDER BY provider
                """
            ).fetchall()
        return [dict(row) for row in rows]
