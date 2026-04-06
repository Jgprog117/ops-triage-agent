import pytest
from backend.agent.parser import (
    extract_json_from_text,
    parse_tool_arguments,
    parse_triage_result,
)
from backend.db.models import TriageResult
from backend.exceptions import ParseError


class TestParseToolArguments:
    def test_valid_json(self):
        assert parse_tool_arguments('{"query": "thermal"}') == {"query": "thermal"}

    def test_nested_json(self):
        result = parse_tool_arguments('{"a": {"b": 1}, "c": [1, 2]}')
        assert result == {"a": {"b": 1}, "c": [1, 2]}

    def test_empty_string(self):
        assert parse_tool_arguments("") is None

    def test_malformed_json(self):
        assert parse_tool_arguments("{query: thermal}") is None

    def test_none_input(self):
        assert parse_tool_arguments(None) is None


class TestExtractJsonFromText:
    def test_direct_json(self):
        result = extract_json_from_text('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_code_fence(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```'
        assert extract_json_from_text(text) == {"key": "value"}

    def test_bare_code_fence(self):
        text = 'Result:\n```\n{"key": "value"}\n```'
        assert extract_json_from_text(text) == {"key": "value"}

    def test_nested_braces(self):
        text = 'Some text {"a": {"b": 1}} more text'
        result = extract_json_from_text(text)
        assert result is not None
        assert result["a"] == {"b": 1}

    def test_no_json(self):
        assert extract_json_from_text("no json here at all") is None

    def test_text_before_json(self):
        text = '   {"classification": "noise", "summary": "ok"}'
        result = extract_json_from_text(text)
        assert result["classification"] == "noise"

    def test_empty_string(self):
        assert extract_json_from_text("") is None


class TestParseTriageResult:
    VALID_TRIAGE = (
        '{"classification": "incident", "root_cause_hypothesis": "GPU overheat",'
        ' "correlated_alert_ids": ["a1"], "remediation_steps": ["reboot"],'
        ' "escalation_required": true, "escalation_reason": "critical temp",'
        ' "summary": "GPU failure", "summary_ja": "GPU障害"}'
    )

    def test_valid_complete(self):
        result = parse_triage_result(self.VALID_TRIAGE)
        assert isinstance(result, TriageResult)
        assert result.classification == "incident"
        assert result.root_cause_hypothesis == "GPU overheat"
        assert result.escalation_required is True
        assert result.correlated_alert_ids == ["a1"]

    def test_minimal_fields(self):
        text = '{"classification": "noise", "summary": "ok", "summary_ja": "ok"}'
        result = parse_triage_result(text)
        assert result is not None
        assert result.classification == "noise"
        assert result.remediation_steps == []
        assert result.escalation_required is False

    def test_field_normalization_root_cause(self):
        text = '{"classification": "acknowledged", "root_cause": "disk failure", "summary": "s", "summary_ja": "s"}'
        result = parse_triage_result(text)
        assert result is not None
        assert result.root_cause_hypothesis == "disk failure"

    def test_invalid_classification(self):
        text = '{"classification": "bogus", "summary": "s", "summary_ja": "s"}'
        with pytest.raises(ParseError):
            parse_triage_result(text)

    def test_garbage_input(self):
        with pytest.raises(ParseError):
            parse_triage_result("not json at all")

    def test_in_code_fence(self):
        text = 'Here is my assessment:\n```json\n' + self.VALID_TRIAGE + '\n```'
        result = parse_triage_result(text)
        assert isinstance(result, TriageResult)
        assert result.classification == "incident"
