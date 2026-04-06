import logging
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.base_url = settings.LLM_API_BASE.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        client = self._get_client()
        logger.debug("LLM request: model=%s, messages=%d, tools=%d",
                     self.model, len(messages), len(tools or []))
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        logger.debug("LLM response: finish_reason=%s",
                     data["choices"][0].get("finish_reason"))
        return data

    def extract_message(self, response: dict[str, Any]) -> dict[str, Any]:
        return response["choices"][0]["message"]

    def has_tool_calls(self, message: dict[str, Any]) -> bool:
        return bool(message.get("tool_calls"))

    def get_tool_calls(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        return message.get("tool_calls", [])

    def get_content(self, message: dict[str, Any]) -> str:
        return message.get("content") or ""


llm = LLMClient()
