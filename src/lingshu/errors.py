class LingShuError(Exception):
    """灵枢可预期错误的基类。"""


class ConfigError(LingShuError):
    """配置无效或缺失。"""


class ProviderError(LingShuError):
    """模型供应商请求失败。"""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "PROVIDER_ERROR",
        response_received: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.response_received = response_received


class StorageError(LingShuError):
    """本地状态或用量记录失败。"""


class BudgetExceededError(LingShuError):
    """按量供应商的试验预算不足。"""


class WorkspaceSecurityError(LingShuError):
    """工作区访问超出允许范围。"""


class ToolExecutionError(LingShuError):
    """受控工具调用失败。"""
