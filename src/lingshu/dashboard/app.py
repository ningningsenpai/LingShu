from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from lingshu.observability.queries import DashboardQueries
from lingshu.settings import AppConfig, load_config
from lingshu.storage import Storage


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_app(config: AppConfig | None = None, storage: Storage | None = None) -> FastAPI:
    """创建只监听本机的灵枢观测应用。"""
    runtime_config = config or load_config()
    runtime_storage = storage or Storage(runtime_config.project_root / "data" / "lingshu.db")
    queries = DashboardQueries(
        runtime_storage.path,
        stale_after_seconds=runtime_config.policies.request_timeout_seconds + 60,
    )
    static_root = Path(__file__).resolve().parent / "static"

    app = FastAPI(
        title="灵枢模型调用观测台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
        www_redirect=False,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 422:
            code = "INVALID_QUERY"
        else:
            code = "REQUEST_FAILED"
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response(422, "INVALID_QUERY", "查询参数无效")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
        return _error_response(500, "INTERNAL_ERROR", "读取观测数据失败")

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "schema_version": Storage._SCHEMA_VERSION}

    @app.get("/api/v1/overview")
    def overview() -> dict[str, Any]:
        return queries.overview()

    @app.get("/api/v1/tasks")
    def tasks(
        status: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        search: str | None = None,
        dispatch: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = queries.list_tasks(
            status=status,
            provider=provider,
            model=model,
            search=search,
            dispatch=dispatch,
            limit=limit,
        )
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        item = queries.task_detail(task_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到指定任务")
        return item

    @app.get("/api/v1/calls")
    def calls(
        source: str = "TASK",
        state: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        items = queries.list_calls(
            source=source,
            state=state,
            provider=provider,
            model=model,
            limit=limit,
        )
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/providers")
    def providers() -> dict[str, Any]:
        return {
            "items": [
                {
                    "name": name,
                    "display_name": provider.display_name,
                    "configured": provider.api_key is not None,
                    "models": [
                        {
                            "alias": alias,
                            "id": model.id,
                            "pricing_mode": model.pricing_mode,
                        }
                        for alias, model in provider.models.items()
                    ],
                }
                for name, provider in runtime_config.providers.items()
            ]
        }

    @app.get("/api/v1/analytics/daily")
    def daily_analytics(
        days: int = Query(default=30, ge=7, le=90),
        start_date: date | None = None,
        end_date: date | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if days not in {7, 30, 90}:
            raise HTTPException(status_code=422, detail="时间范围只支持近 7、30 或 90 天")
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=422, detail="自定义时间必须同时提供开始和结束日期")
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
            if (end_date - start_date).days > 365:
                raise HTTPException(status_code=422, detail="自定义时间最多支持 366 天")
        if provider is not None and provider not in runtime_config.providers:
            raise HTTPException(status_code=422, detail="未知的 Provider")
        return queries.daily_analytics(
            runtime_config.providers,
            days=days,
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            model=model,
        )

    if static_root.is_dir():
        assets = static_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_root / "index.html")

    return app
