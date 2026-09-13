from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COLLECTED = "COLLECTED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    FAILED = "FAILED"


class CallState(StrEnum):
    ATTEMPTING = "ATTEMPTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    TIMED_OUT = "TIMED_OUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    CANCELLED = "CANCELLED"


class CallSource(StrEnum):
    TASK = "TASK"
    DOCTOR = "DOCTOR"


class PricingMode(StrEnum):
    METERED = "METERED"
    SUBSCRIPTION = "SUBSCRIPTION"
    UNKNOWN = "UNKNOWN"


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelRequest(BaseModel):
    task_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = "auto"
    temperature: float = 0.1
    max_output_tokens: int = Field(default=8000, gt=0)
    timeout_seconds: float = Field(default=180, gt=0)
    source: CallSource = CallSource.TASK


class ModelResponse(BaseModel):
    provider: str
    model: str
    request_id: str | None = None
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0, ge=0)
    finish_reason: str | None = None
    usage_reported: bool = False


class RouteDecision(BaseModel):
    provider: str
    model_alias: str
    rule_name: str


class TaskRecord(BaseModel):
    task_id: str
    status: TaskStatus
    prompt: str
    provider: str | None = None
    model_alias: str | None = None
    workspace: Path
    result_path: Path | None = None
    error: str | None = None
    risk: RiskLevel = "normal"
    route_rule: str | None = None
    failure_phase: str | None = None


class DoctorResult(BaseModel):
    provider: str
    display_name: str
    configured: bool
    live_checked: bool = False
    ok: bool = False
    detail: str


RiskLevel = Literal["low", "normal", "high"]
