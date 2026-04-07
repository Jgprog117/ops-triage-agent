"""Provider-agnostic HTTP client for OpenAI- and Anthropic-style chat APIs.

The :class:`LLMClient` exposes a single ``chat_completion`` surface and
hides the format differences between OpenAI's ``/v1/chat/completions``
endpoint and Anthropic's ``/v1/messages`` endpoint. Anthropic responses
are normalized into the OpenAI shape so the rest of the codebase only
needs to know one format. Retries with exponential backoff and the
custom :class:`backend.exceptions.LLMError` taxonomy live here.
"""

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from backend.config import settings
from backend.exceptions import (
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class LLMClient:
    """HTTP client that wraps the configured LLM provider.

    The instance reads its provider, base URL, API key, and model from
    :data:`backend.config.settings` at construction time. The underlying
    :class:`httpx.AsyncClient` is created lazily on first use and reused
    for all subsequent calls until :meth:`close` is invoked.

    Attributes:
        provider: The lowercase provider id (``anthropic`` or ``openai``).
        base_url: The HTTP base URL for the provider, without trailing
            slash.
        api_key: The provider API key.
        model: The model name passed in every request body.
    """

    def __init__(self) -> None:
        """Reads provider config from settings and prepares the client."""
        self.provider = settings.LLM_PROVIDER.lower()
        self.base_url = (settings.LLM_API_BASE or DEFAULT_BASES.get(self.provider, "")).rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Returns the lazily-instantiated shared httpx client.

        Returns:
            The shared :class:`httpx.AsyncClient`, created on first call.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT)
        return self._client

    async def close(self) -> None:
        """Closes the underlying httpx client if one was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        _max_retries: int | None = None,
    ) -> dict[str, Any]:
        """Sends a chat-completion request to the configured provider.

        Routes to either :meth:`_anthropic_completion` or
        :meth:`_openai_completion` based on :attr:`provider`. Retries
        timeouts, 429s, and 5xx responses with exponential backoff.
        Non-retryable 4xx errors propagate immediately.

        Args:
            messages: OpenAI-style message list. Anthropic-format
                messages must be converted by the caller — internally
                this method always normalizes to OpenAI shape.
            tools: Optional OpenAI-style tool definitions. When provided
                they are forwarded to the model with ``tool_choice=auto``.
            temperature: Sampling temperature in ``[0, 2]``.
            _max_retries: Internal override for the retry count. Tests
                use this to keep iteration counts small.

        Returns:
            The response body in OpenAI ``chat.completion`` shape.

        Raises:
            LLMTimeoutError: When all retries hit a network timeout.
            LLMRateLimitError: When all retries returned HTTP 429.
            LLMServerError: When all retries returned 5xx, or for the
                degenerate case where the loop exits with no result.
            httpx.HTTPStatusError: For non-retryable 4xx responses.
        """
        max_retries = _max_retries if _max_retries is not None else settings.LLM_MAX_RETRIES

        for attempt in range(max_retries):
            try:
                if self.provider == "anthropic":
                    return await self._anthropic_completion(messages, tools, temperature)
                return await self._openai_completion(messages, tools, temperature)
            except httpx.TimeoutException:
                if attempt == max_retries - 1:
                    raise LLMTimeoutError(
                        f"LLM request timed out after {max_retries} attempts"
                    )
                delay = min(2 ** attempt, 30) + random.uniform(0, 1)
                logger.warning("LLM timeout, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, max_retries)
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                is_last = attempt == max_retries - 1

                if status == 429:
                    if is_last:
                        raise LLMRateLimitError(
                            f"Rate limited after {max_retries} retries"
                        )
                    retry_after = float(e.response.headers.get("retry-after", 2 ** attempt))
                    jitter = random.uniform(0, 1)
                    logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)", retry_after + jitter, attempt + 1, max_retries)
                    await asyncio.sleep(retry_after + jitter)
                elif 500 <= status < 600:
                    if is_last:
                        raise LLMServerError(
                            f"LLM server error {status} after {max_retries} retries"
                        )
                    delay = min(2 ** attempt, 30) + random.uniform(0, 1)
                    logger.warning("LLM server error %d, retrying in %.1fs (attempt %d/%d)", status, delay, attempt + 1, max_retries)
                    await asyncio.sleep(delay)
                else:
                    raise  # 4xx (non-429) — don't retry

        raise LLMServerError("unreachable — retry loop exited without return or raise")

    # -- OpenAI-compatible path ------------------------------------------------

    async def _openai_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        """Performs a single chat-completion call against an OpenAI endpoint.

        Args:
            messages: OpenAI-style message list.
            tools: Optional OpenAI-style tool definitions.
            temperature: Sampling temperature.

        Returns:
            The decoded JSON response body.

        Raises:
            httpx.HTTPStatusError: For any non-2xx response.
            httpx.TimeoutException: When the request exceeds the
                configured timeout.
        """
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
        """Performs a single chat-completion call against Anthropic.

        Converts OpenAI-shaped messages and tools to Anthropic format,
        sends the request, and converts the response back to the OpenAI
        shape so callers see a single format.

        Args:
            messages: OpenAI-style message list.
            tools: Optional OpenAI-style tool definitions.
            temperature: Sampling temperature.

        Returns:
            The Anthropic response normalized to OpenAI shape.

        Raises:
            httpx.HTTPStatusError: For any non-2xx response.
            httpx.TimeoutException: When the request exceeds the
                configured timeout.
        """
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
        """Converts OpenAI-style messages to Anthropic format.

        Splits the system prompt out (Anthropic accepts ``system`` as a
        top-level field, not a message), unpacks ``tool_calls`` into
        ``tool_use`` content blocks on assistant turns, and merges
        consecutive ``tool`` results into one user-role message of
        ``tool_result`` blocks (which Anthropic requires).

        Args:
            messages: OpenAI-shaped message list.

        Returns:
            A two-tuple ``(system, messages)`` where ``system`` is the
            extracted system prompt (empty string when none was set) and
            ``messages`` is the Anthropic-shaped message list.
        """
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
        """Converts OpenAI-style tool definitions to Anthropic format.

        Args:
            tools: OpenAI-style tool definitions, each wrapping a
                ``function`` object with ``name``, ``description``, and
                ``parameters``.

        Returns:
            A list of Anthropic-style tool definitions with ``name``,
            ``description``, and ``input_schema`` fields.
        """
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
        """Normalizes an Anthropic response into the OpenAI shape.

        Joins text content blocks into a single ``content`` string,
        repackages ``tool_use`` blocks as OpenAI ``tool_calls`` entries,
        and maps the ``stop_reason`` to a matching ``finish_reason``.

        Args:
            data: The decoded Anthropic ``messages`` response body.

        Returns:
            An OpenAI ``chat.completion``-shaped dict with a single choice.
        """
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
        """Pulls the assistant message out of an OpenAI-shaped response.

        Args:
            response: A response body in OpenAI ``chat.completion`` shape.

        Returns:
            The first ``choices[0].message`` dict.

        Raises:
            LLMResponseError: When the response is missing the expected
                fields.
        """
        try:
            return response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMResponseError(
                f"Malformed LLM response: {e}", raw_response=response
            ) from e

    def has_tool_calls(self, message: dict[str, Any]) -> bool:
        """Returns ``True`` when the message contains any ``tool_calls``.

        Args:
            message: An assistant message dict.
        """
        return bool(message.get("tool_calls"))

    def get_tool_calls(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Returns the ``tool_calls`` list, or an empty list when absent.

        Args:
            message: An assistant message dict.
        """
        return message.get("tool_calls", [])

    def get_content(self, message: dict[str, Any]) -> str:
        """Returns the message text content, or empty string when absent.

        Args:
            message: An assistant message dict.
        """
        return message.get("content") or ""


llm = LLMClient()
