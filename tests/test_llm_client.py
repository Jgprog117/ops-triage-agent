from backend.llm.client import LLMClient


def _mock_response(content="hello", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


class TestLLMClientUtilities:
    def setup_method(self):
        self.client = LLMClient()

    def test_extract_message(self):
        resp = _mock_response(content="test")
        msg = self.client.extract_message(resp)
        assert msg["content"] == "test"
        assert msg["role"] == "assistant"

    def test_has_tool_calls_true(self):
        resp = _mock_response(tool_calls=[{"id": "1", "function": {"name": "f", "arguments": "{}"}}])
        msg = self.client.extract_message(resp)
        assert self.client.has_tool_calls(msg) is True

    def test_has_tool_calls_false(self):
        msg = self.client.extract_message(_mock_response())
        assert self.client.has_tool_calls(msg) is False

    def test_get_tool_calls(self):
        calls = [{"id": "1", "function": {"name": "f", "arguments": "{}"}}]
        msg = self.client.extract_message(_mock_response(tool_calls=calls))
        assert self.client.get_tool_calls(msg) == calls

    def test_get_content(self):
        msg = self.client.extract_message(_mock_response(content="hello world"))
        assert self.client.get_content(msg) == "hello world"

    def test_get_content_none(self):
        msg = {"role": "assistant", "content": None}
        assert self.client.get_content(msg) == ""
