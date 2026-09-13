from __future__ import annotations

import os
from math import isfinite
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from lingshu.errors import ConfigError


class ModelConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    id: str = Field(min_length=1)
    currency: Literal["CNY", "USD"] = "CNY"
    input_price_per_million: float | None = Field(default=None, ge=0)
    cached_input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    pricing_mode: Literal["METERED", "SUBSCRIPTION", "UNKNOWN"] = "UNKNOWN"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    display_name: str = Field(min_length=1)
    base_url_env: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    default_base_url: str = Field(min_length=1)
    budget_env: str | None = None
    default_budget_cny: float | None = Field(default=None, ge=0)
    models: dict[str, ModelConfig] = Field(min_length=1)

    @property
    def base_url(self) -> str:
        value = os.getenv(self.base_url_env, self.default_base_url).strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
        except ValueError as exc:
            raise ConfigError(f"环境变量 {self.base_url_env} 不是有效地址") from exc
        is_local_http = parsed.scheme == "http" and hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not hostname
            or (parsed.scheme != "https" and not is_local_http)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigError(
                f"环境变量 {self.base_url_env} 必须是 HTTPS 地址；仅本机回环地址可使用 HTTP"
            )
        return value

    @property
    def api_key(self) -> str | None:
        value = os.getenv(self.api_key_env, "").strip()
        return value or None

    @property
    def budget_cny(self) -> float | None:
        if not self.budget_env:
            return self.default_budget_cny
        value = os.getenv(self.budget_env, "").strip()
        if not value:
            return self.default_budget_cny
        try:
            budget = float(value)
        except ValueError as exc:
            raise ConfigError(f"环境变量 {self.budget_env} 必须是数字") from exc
        if not isfinite(budget) or budget < 0:
            raise ConfigError(f"环境变量 {self.budget_env} 必须是非负有限数字")
        return budget


class PolicyConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    max_tool_rounds: int = Field(default=6, ge=0)
    max_calls_per_task: int = Field(default=8, gt=0)
    max_revisions: int = Field(default=2, ge=0)
    request_timeout_seconds: float = Field(default=180, gt=0)
    max_output_tokens: int = Field(default=8000, gt=0)
    max_file_chars: int = Field(default=80000, gt=0)
    max_search_results: int = Field(default=100, gt=0)
    max_listed_files: int = Field(default=500, gt=0)
    artifact_name_max_length: int = Field(default=120, gt=0)
    max_artifact_chars: int = Field(default=200000, gt=0)


class AppConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    project_root: Path
    providers: dict[str, ProviderConfig]
    routing: dict[str, Any]
    policies: PolicyConfig
    allowed_workspaces: list[Path] = Field(default_factory=list)
    live_tests_enabled: bool = False
    usd_cny_rate: float = Field(default=7.2, gt=0)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"缺少配置文件：{path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 配置格式错误：{path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是对象：{path}")
    return data


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_allowed_workspaces(project_root: Path) -> list[Path]:
    value = os.getenv("LINGSHU_ALLOWED_WORKSPACES", "").strip()
    if not value:
        return [project_root.resolve()]
    roots = [Path(item.strip()).expanduser().resolve() for item in value.split(";") if item.strip()]
    if not roots:
        raise ConfigError("LINGSHU_ALLOWED_WORKSPACES 未包含有效目录")
    return roots


def load_config(project_root: Path | None = None) -> AppConfig:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    load_dotenv(root / ".env", override=False)

    models = _read_yaml(root / "config" / "models.yaml")
    routing = _read_yaml(root / "config" / "routing.yaml")
    policies = _read_yaml(root / "config" / "policies.yaml")

    try:
        raw_providers = models["providers"]
        if not isinstance(raw_providers, dict) or not raw_providers:
            raise TypeError("providers 不是非空对象")
        providers = {
            name: ProviderConfig.model_validate(provider)
            for name, provider in raw_providers.items()
        }
        usd_cny_rate = float(os.getenv("LINGSHU_USD_CNY_RATE", "7.2"))
        return AppConfig(
            project_root=root,
            providers=providers,
            routing=routing,
            policies=PolicyConfig.model_validate(policies),
            allowed_workspaces=_parse_allowed_workspaces(root),
            live_tests_enabled=_parse_bool(os.getenv("LINGSHU_ENABLE_LIVE_TESTS")),
            usd_cny_rate=usd_cny_rate,
        )
    except ConfigError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("模型配置缺少必要字段或字段类型错误") from exc
