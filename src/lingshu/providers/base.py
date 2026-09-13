from __future__ import annotations

from abc import ABC, abstractmethod

from lingshu.schemas import ModelRequest, ModelResponse


class BaseProvider(ABC):
    """供应商适配器的最小接口。"""

    name: str

    @abstractmethod
    async def chat(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def aclose(self) -> None:
        """关闭由适配器持有的资源；无资源的实现无需处理。"""
        return None
