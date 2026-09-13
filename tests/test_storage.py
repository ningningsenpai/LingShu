import sqlite3
from pathlib import Path

import pytest

from lingshu.errors import BudgetExceededError, StorageError
from lingshu.schemas import CallSource, ModelResponse, TaskStatus, Usage
from lingshu.settings import ModelConfig
from lingshu.storage import Storage


def test_budget_reservation_prevents_concurrent_overspend(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    first = storage.reserve_budget("task-1", "deepseek", 6, 10)

    with pytest.raises(BudgetExceededError, match="预算不足"):
        storage.reserve_budget("task-2", "deepseek", 5, 10)

    storage.settle_budget(first, 4)
    second = storage.reserve_budget("task-2", "deepseek", 6, 10)
    assert second is not None


def test_released_reservation_no_longer_consumes_budget(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    reservation = storage.reserve_budget("task-1", "bailian", 10, 10)
    storage.release_budget(reservation)

    assert storage.reserve_budget("task-2", "bailian", 10, 10) is not None
    assert storage.spent_cny("bailian") == 0


def test_settlement_and_call_record_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = Storage(tmp_path / "test.db")
    reservation = storage.reserve_budget("task-1", "deepseek", 5, 10)

    def fail_insert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("模拟写入失败")

    monkeypatch.setattr(Storage, "_insert_call", staticmethod(fail_insert))
    with pytest.raises(RuntimeError, match="模拟写入失败"):
        storage.settle_and_record_call(
            reservation,
            "task-1",
            ModelResponse(provider="deepseek", model="deepseek-v4-flash"),
            "deepseek",
            "deepseek-v4-flash",
        )

    with storage._connect() as connection:
        state = connection.execute("SELECT state FROM budget_events").fetchone()[0]
        call_count = connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    assert state == "reserved"
    assert call_count == 0


def test_negative_budget_amount_is_rejected(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")

    with pytest.raises(ValueError, match="非负"):
        storage.reserve_budget("task-1", "deepseek", -1, 10)


def test_updating_missing_task_is_rejected(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")

    with pytest.raises(StorageError, match="找不到"):
        storage.update_task("missing", TaskStatus.FAILED)


def test_call_lifecycle_records_attempt_usage_and_pricing(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    model = ModelConfig(
        id="test-model",
        pricing_mode="METERED",
        input_price_per_million=1,
        output_price_per_million=2,
    )

    call_id, reservation_id = storage.begin_call_and_reserve(
        task_id="task-1",
        source=CallSource.TASK,
        provider="test",
        model="test-model",
        model_alias="default",
        reservation_amount_cny=2,
        budget_limit_cny=10,
        model_config=model,
        usd_cny_rate=7.2,
        pricing_config_version="version-1",
    )
    with storage._connect() as connection:
        attempt = connection.execute(
            "SELECT state, source, call_seq FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
    assert tuple(attempt) == ("ATTEMPTING", "TASK", 1)

    storage.complete_call(
        call_id=call_id,
        reservation_id=reservation_id,
        response=ModelResponse(
            provider="test",
            model="test-model",
            usage=Usage(input_tokens=100, cached_input_tokens=20, output_tokens=10),
            usage_reported=True,
            latency_ms=15,
            estimated_cost_cny=0.0001,
        ),
        duration_ms=18,
    )

    with storage._connect() as connection:
        call = connection.execute(
            """
            SELECT state, usage_reported, duration_ms, pricing_mode, ok
            FROM calls WHERE call_id = ?
            """,
            (call_id,),
        ).fetchone()
        budget = connection.execute(
            "SELECT state, amount_cny FROM budget_events WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
    assert tuple(call) == ("SUCCEEDED", 1, 18, "METERED", 1)
    assert tuple(budget) == ("settled", 0.0001)


def test_failed_call_and_budget_release_are_atomic(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    model = ModelConfig(id="test-model", pricing_mode="METERED")
    call_id, reservation_id = storage.begin_call_and_reserve(
        task_id="task-1",
        source=CallSource.TASK,
        provider="test",
        model="test-model",
        model_alias="default",
        reservation_amount_cny=2,
        budget_limit_cny=10,
        model_config=model,
        usd_cny_rate=7.2,
        pricing_config_version="version-1",
    )

    with pytest.raises(StorageError, match="待完成"):
        storage.fail_call(
            call_id="missing",
            reservation_id=reservation_id,
            state="TIMED_OUT",
            error_type="TIMED_OUT",
            error="请求超时",
            duration_ms=20,
        )

    with storage._connect() as connection:
        call_state = connection.execute(
            "SELECT state FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()[0]
        budget_state = connection.execute(
            "SELECT state FROM budget_events WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()[0]
    assert call_state == "ATTEMPTING"
    assert budget_state == "reserved"


def test_legacy_database_is_migrated_without_losing_usage(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY, status TEXT NOT NULL, prompt TEXT NOT NULL,
                provider TEXT NOT NULL, model_alias TEXT NOT NULL, workspace TEXT NOT NULL,
                result_path TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE calls (
                call_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL, estimated_cost_cny REAL NOT NULL,
                ok INTEGER NOT NULL, error TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE budget_events (
                reservation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                provider TEXT NOT NULL, amount_cny REAL NOT NULL, state TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO tasks VALUES (
                'task-1', 'ACCEPTED', '测试', 'ark_coding', 'glm_primary', '.',
                NULL, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00'
            );
            INSERT INTO calls VALUES (
                'call-1', 'task-1', 'ark_coding', 'glm-5.3', 100, 40, 20, 50,
                0, 1, NULL, '2026-01-01T00:00:00+00:00'
            );
            INSERT INTO calls VALUES (
                'call-2', 'doctor-ark', 'ark_coding', 'glm-5.3-flash', 1, 0, 1, 10,
                0, 1, NULL, '2026-01-01T00:00:02+00:00'
            );
            """
        )

    storage = Storage(path)
    with storage._connect() as connection:
        task_call = connection.execute(
            """
            SELECT state, source, input_tokens, cached_input_tokens
            FROM calls WHERE call_id='call-1'
            """
        ).fetchone()
        doctor_call = connection.execute(
            "SELECT task_id, correlation_id, source FROM calls WHERE call_id='call-2'"
        ).fetchone()
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]

    assert tuple(task_call) == ("SUCCEEDED", "TASK", 100, 40)
    assert tuple(doctor_call) == (None, "doctor-ark", "DOCTOR")
    assert version == 1
    assert path.with_name("legacy.pre-dashboard-v1.bak").is_file()

    Storage(path)
    with storage._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 2
