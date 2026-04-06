"""Minimal, model-agnostic LLM client using the OpenAI-compatible API.

Works with any OpenAI-compatible endpoint: OpenAI, Anthropic, Ollama, vLLM,
or ai&'s own inference infrastructure. Zero third-party LLM SDK dependencies
— just httpx for HTTP calls. This is a deliberate architectural choice to
minimize supply chain attack surface for internal tooling.
"""

import logging
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Async client for OpenAI-compatible chat completion endpoints."""

    def __init__(self) -> None:
        self.base_url = settings.LLM_API_BASE.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Send a chat completion request and return the parsed response.

        Args:
            messages: Conversation messages in OpenAI format.
            tools: Optional tool/function definitions for tool-use.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            The full API response as a dictionary.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
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

        async with httpx.AsyncClient(timeout=60) as client:
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
        """Extract the assistant message from an API response."""
        return response["choices"][0]["message"]

    def has_tool_calls(self, message: dict[str, Any]) -> bool:
        """Check if the assistant message contains tool calls."""
        return bool(message.get("tool_calls"))

    def get_tool_calls(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract tool calls from the assistant message."""
        return message.get("tool_calls", [])

    def get_content(self, message: dict[str, Any]) -> str:
        """Extract text content from the assistant message."""
        return message.get("content") or ""


llm = LLMClient()
