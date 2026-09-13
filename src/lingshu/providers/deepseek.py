import httpx

from lingshu.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None
    ) -> None:
        super().__init__("deepseek", base_url, api_key, client)
