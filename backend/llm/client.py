import json
import logging
import uuid
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER.lower()
        self.base_url = (settings.LLM_API_BASE or DEFAULT_BASES.get(self.provider, "")).rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120)
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
        if self.provider == "anthropic":
            return await self._anthropic_completion(messages, tools, temperature)
        return await self._openai_completion(messages, tools, temperature)

    # -- OpenAI-compatible path (unchanged) ------------------------------------

    async def _openai_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        client = self._get_client()
        logger.debug("LLM request [openai]: model=%s, messages=%d", self.model, len(messages))
        response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    # -- Anthropic path --------------------------------------------------------

    async def _anthropic_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        system, converted_messages = self._to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": converted_messages,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._to_anthropic_tools(tools)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        client = self._get_client()
        logger.debug("LLM request [anthropic]: model=%s, messages=%d", self.model, len(converted_messages))
        response = await client.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        return self._from_anthropic_response(response.json())

    def _to_anthropic_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system = ""
        result: list[dict[str, Any]] = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system = msg["content"]

            elif role == "user":
                result.append({"role": "user", "content": msg["content"]})

            elif role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    fn = tc["function"]
                    args = fn["arguments"]
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": fn["name"],
                        "input": json.loads(args) if isinstance(args, str) else args,
                    })
                result.append({"role": "assistant", "content": content_blocks})

            elif role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": msg["content"],
                }
                # Anthropic requires tool_result blocks in a user message.
                # Merge consecutive tool results into one user message.
                if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                    result[-1]["content"].append(tool_result_block)
                else:
                    result.append({"role": "user", "content": [tool_result_block]})

        return system, result

    def _to_anthropic_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools:
            fn = tool["function"]
            converted.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return converted

    def _from_anthropic_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize Anthropic response into OpenAI format so downstream code is unchanged."""
        text_parts = []
        tool_calls = []

        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    },
                })

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        stop_reason = data.get("stop_reason", "end_turn")
        finish_reason = "tool_calls" if stop_reason == "tool_use" else "stop"

        return {
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": data.get("usage", {}),
        }

    # -- Shared accessors (work with normalized OpenAI format) -----------------

    def extract_message(self, response: dict[str, Any]) -> dict[str, Any]:
        return response["choices"][0]["message"]

    def has_tool_calls(self, message: dict[str, Any]) -> bool:
        return bool(message.get("tool_calls"))

    def get_tool_calls(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        return message.get("tool_calls", [])

    def get_content(self, message: dict[str, Any]) -> str:
        return message.get("content") or ""


llm = LLMClient()
