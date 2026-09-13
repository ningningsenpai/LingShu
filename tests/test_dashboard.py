from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from lingshu.dashboard import create_app
from lingshu.schemas import CallSource, ModelResponse, TaskRecord, TaskStatus, Usage
from lingshu.settings import ModelConfig, load_config
from lingshu.storage import Storage


def _client(tmp_path: Path) -> tuple[TestClient, Storage]:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root).model_copy(update={"project_root": tmp_path})
    storage = Storage(tmp_path / "lingshu.db")
    return TestClient(create_app(config, storage)), storage


def test_dashboard_overview_and_task_detail(tmp_path: Path) -> None:
    client, storage = _client(tmp_path)
    storage.create_task(
        TaskRecord(
            task_id="task-1",
            status=TaskStatus.RECEIVED,
            prompt=(
                '检查 API_KEY=very-secret-value 和 '
                '{"Authorization":"Basic another-secret"} 的代码'
            ),
            provider="ark_coding",
            model_alias="glm_primary",
            workspace=tmp_path,
        )
    )
    storage.update_task("task-1", TaskStatus.ACCEPTED)
    storage.record_call(
        "task-1",
        ModelResponse(
            provider="ark_coding",
            model="glm-5.3",
            usage=Usage(input_tokens=100, cached_input_tokens=40, output_tokens=20),
            latency_ms=25,
        ),
        "ark_coding",
        "glm-5.3",
    )

    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["tasks"]["accepted"] == 1
    assert overview.json()["tokens"]["cached_input"] == 40

    tasks = client.get("/api/v1/tasks")
    assert tasks.status_code == 200
    item = tasks.json()["items"][0]
    assert item["dispatch_state"] == "RESPONDED"
    assert "very-secret-value" not in item["prompt_preview"]
    assert "another-secret" not in item["prompt_preview"]
    assert "workspace" not in item

    detail = client.get("/api/v1/tasks/task-1")
    assert detail.status_code == 200
    assert detail.json()["calls"][0]["display_state"] == "SUCCEEDED"
    assert "Content-Security-Policy" in detail.headers
    assert "Access-Control-Allow-Origin" not in detail.headers


def test_dashboard_uses_stable_error_shape(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/api/v1/tasks/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "找不到指定任务"}
    }


def test_dashboard_treats_stale_attempt_as_unknown(tmp_path: Path) -> None:
    client, storage = _client(tmp_path)
    storage.create_task(
        TaskRecord(
            task_id="task-stale",
            status=TaskStatus.DISPATCHED,
            prompt="测试中断调用",
            provider="deepseek",
            model_alias="default",
            workspace=tmp_path,
        )
    )
    call_id, _ = storage.begin_call_and_reserve(
        task_id="task-stale",
        source=CallSource.TASK,
        provider="deepseek",
        model="deepseek-v4-flash",
        model_alias="default",
        reservation_amount_cny=0,
        budget_limit_cny=None,
        model_config=ModelConfig(id="deepseek-v4-flash", pricing_mode="METERED"),
        usd_cny_rate=7.2,
        pricing_config_version="test",
    )
    stale_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with storage._connect() as connection:
        connection.execute(
            "UPDATE calls SET started_at = ? WHERE call_id = ?", (stale_time, call_id)
        )

    overview = client.get("/api/v1/overview").json()
    task = client.get("/api/v1/tasks").json()["items"][0]
    detail = client.get("/api/v1/tasks/task-stale").json()

    assert overview["calls"]["attempting"] == 0
    assert overview["calls"]["stale"] == 1
    assert overview["calls"]["outcome_unknown"] == 1
    assert task["dispatch_state"] == "OUTCOME_UNKNOWN"
    assert detail["calls"][0]["display_state"] == "STALE"


def test_dashboard_rejects_untrusted_host(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/api/v1/health", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_daily_analytics_uses_shanghai_days_and_excludes_doctor(tmp_path: Path) -> None:
    client, storage = _client(tmp_path)
    shanghai_timezone = timezone(timedelta(hours=8), "Asia/Shanghai")
    local_today = datetime.now(shanghai_timezone).date()

    def add_task_call(
        task_id: str,
        provider: str,
        alias: str,
        model: str,
        usage: Usage,
        local_date_offset: int,
    ) -> None:
        storage.create_task(
            TaskRecord(
                task_id=task_id,
                status=TaskStatus.ACCEPTED,
                prompt="聚合测试",
                provider=provider,
                model_alias=alias,
                workspace=tmp_path,
            )
        )
        storage.record_call(
            task_id,
            ModelResponse(
                provider=provider,
                model=model,
                usage=usage,
                usage_reported=True,
            ),
            provider,
            model,
        )
        local_date = local_today - timedelta(days=local_date_offset)
        local_timestamp = datetime.combine(
            local_date, time(hour=0, minute=30), shanghai_timezone
        )
        with storage._connect() as connection:
            connection.execute(
                "UPDATE calls SET created_at = ?, started_at = ? WHERE task_id = ?",
                (
                    local_timestamp.astimezone(UTC).isoformat(),
                    local_timestamp.astimezone(UTC).isoformat(),
                    task_id,
                ),
            )

    add_task_call(
        "task-ark",
        "ark_coding",
        "deepseek_flash",
        "deepseek-v4-flash",
        Usage(input_tokens=100, cached_input_tokens=40, output_tokens=20),
        0,
    )
    add_task_call(
        "task-deepseek",
        "deepseek",
        "default",
        "deepseek-v4-flash",
        Usage(input_tokens=200, cached_input_tokens=50, output_tokens=30),
        1,
    )
    add_task_call(
        "task-deepseek-metered",
        "deepseek",
        "default",
        "deepseek-v4-flash",
        Usage(input_tokens=10, output_tokens=2),
        0,
    )
    with storage._connect() as connection:
        connection.execute(
            "UPDATE calls SET pricing_mode = 'METERED' WHERE task_id = ?",
            ("task-deepseek-metered",),
        )
    doctor_id, _ = storage.begin_call_and_reserve(
        task_id="doctor-analytics",
        source=CallSource.DOCTOR,
        provider="ark_coding",
        model="glm-5.3",
        model_alias="glm_primary",
        reservation_amount_cny=0,
        budget_limit_cny=None,
        model_config=ModelConfig(id="glm-5.3", pricing_mode="SUBSCRIPTION"),
        usd_cny_rate=7.2,
        pricing_config_version="test",
    )
    storage.complete_call(
        call_id=doctor_id,
        reservation_id=None,
        response=ModelResponse(
            provider="ark_coding",
            model="glm-5.3",
            usage=Usage(input_tokens=999, output_tokens=999),
            usage_reported=True,
        ),
        duration_ms=1,
    )

    response = client.get("/api/v1/analytics/daily?days=7")
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert payload["timezone"] == "Asia/Shanghai"
    assert len(payload["days"]) == 7
    assert [item["label"] for item in payload["days"][-3:]] == [
        "前天",
        "昨天",
        "今天",
    ]
    assert [item["display_name"] for item in payload["providers"]] == [
        "方舟 Coding Plan",
        "DeepSeek 官方",
        "阿里云百炼",
    ]
    ark = payload["providers"][0]
    ark_model = next(
        item for item in ark["models"] if item["model"] == "deepseek-v4-flash"
    )
    assert ark["totals"]["attempts"] == 1
    assert ark_model["days"][-1]["total_tokens"] == 120
    assert ark_model["days"][-1]["cached_input_tokens"] == 40
    assert ark_model["days"][-1]["non_cached_input_tokens"] == 60
    deepseek = payload["providers"][1]
    deepseek_models = [
        item for item in deepseek["models"] if item["model"] == "deepseek-v4-flash"
    ]
    assert len(deepseek_models) == 1
    assert deepseek_models[0]["days"][-2]["total_tokens"] == 230
    assert deepseek_models[0]["days"][-1]["total_tokens"] == 12
    assert payload["totals"]["total_tokens"] == 362

    filtered = client.get(
        "/api/v1/analytics/daily",
        params={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "start_date": (local_today - timedelta(days=1)).isoformat(),
            "end_date": local_today.isoformat(),
        },
    ).json()
    assert filtered["range"]["days"] == 2
    assert [item["provider"] for item in filtered["providers"]] == ["deepseek"]
    assert filtered["totals"]["attempts"] == 2
    assert filtered["totals"]["total_tokens"] == 242


def test_daily_analytics_rejects_invalid_ranges(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    for query in (
        "days=10",
        "start_date=2026-01-01",
        "start_date=2026-01-02&end_date=2026-01-01",
        "start_date=2025-01-01&end_date=2026-01-02",
        "provider=missing",
    ):
        response = client.get(f"/api/v1/analytics/daily?{query}")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_QUERY"
