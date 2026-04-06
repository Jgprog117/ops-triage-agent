import json

import pytest
import httpx

from backend.exceptions import (
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
    LLMTimeoutError,
    ParseError,
)
from backend.llm.client import LLMClient
from backend.agent.parser import (
    extract_json_from_text,
    parse_triage_result,
)


class TestExtractMessageErrors:
    def test_empty_response_raises(self):
        client = LLMClient()
        with pytest.raises(LLMResponseError):
            client.extract_message({})

    def test_empty_choices_raises(self):
        client = LLMClient()
        with pytest.raises(LLMResponseError):
            client.extract_message({"choices": []})

    def test_missing_message_raises(self):
        client = LLMClient()
        with pytest.raises(LLMResponseError):
            client.extract_message({"choices": [{}]})

    def test_none_response_raises(self):
        client = LLMClient()
        with pytest.raises(LLMResponseError):
            client.extract_message(None)


class TestParserErrorPaths:
    def test_deeply_nested_json(self):
        """Bracket-counting should handle 3+ levels of nesting."""
        text = 'result: {"a": {"b": {"c": {"d": 1}}}}'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["a"]["b"]["c"]["d"] == 1

    def test_json_with_string_braces(self):
        """Braces inside strings should not confuse the parser."""
        text = 'out: {"msg": "use {curly} braces", "val": 1}'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["val"] == 1

    def test_multiline_code_fence(self):
        """Fenced JSON spanning multiple lines should parse."""
        text = '```json\n{\n  "classification": "noise",\n  "summary": "ok"\n}\n```'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["classification"] == "noise"

    def test_parse_triage_raises_on_garbage(self):
        with pytest.raises(ParseError) as exc_info:
            parse_triage_result("this is not json at all")
        assert exc_info.value.raw_content == "this is not json at all"

    def test_parse_triage_raises_on_invalid_enum(self):
        text = '{"classification": "invalid_value", "summary": "s", "summary_ja": "s"}'
        with pytest.raises(ParseError):
            parse_triage_result(text)

    def test_parse_tool_arguments_with_wrapped_json(self):
        from backend.agent.parser import parse_tool_arguments
        # LLM wraps args in markdown
        raw = '```json\n{"query": "thermal"}\n```'
        result = parse_tool_arguments(raw)
        assert result == {"query": "thermal"}

    def test_parse_tool_arguments_none(self):
        from backend.agent.parser import parse_tool_arguments
        assert parse_tool_arguments(None) is None

    def test_code_fence_without_newlines(self):
        """Fenced JSON without strict newlines should still parse."""
        text = '```json {"key": "value"} ```'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["key"] == "value"


class TestLLMExceptionTypes:
    def test_rate_limit_error(self):
        e = LLMRateLimitError("rate limited")
        assert isinstance(e, Exception)
        assert "rate limited" in str(e)

    def test_server_error(self):
        e = LLMServerError("500 error")
        assert isinstance(e, Exception)

    def test_timeout_error(self):
        e = LLMTimeoutError("timed out")
        assert isinstance(e, Exception)

    def test_response_error_with_raw(self):
        raw = {"bad": "response"}
        e = LLMResponseError("malformed", raw_response=raw)
        assert e.raw_response == raw

    def test_parse_error_with_content(self):
        e = ParseError("parse failed", raw_content="garbage")
        assert e.raw_content == "garbage"
