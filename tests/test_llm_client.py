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


class TestAnthropicConversion:
    def setup_method(self):
        self.client = LLMClient()

    def test_system_message_extracted(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, converted = self.client._to_anthropic_messages(messages)
        assert system == "You are helpful."
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_tool_calls_converted(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "search", "arguments": '{"q": "test"}'}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
        ]
        _, converted = self.client._to_anthropic_messages(messages)
        assert len(converted) == 3
        # Assistant message has tool_use block
        asst = converted[1]
        assert asst["content"][0]["type"] == "tool_use"
        assert asst["content"][0]["name"] == "search"
        assert asst["content"][0]["input"] == {"q": "test"}
        # Tool result is in a user message
        tool_msg = converted[2]
        assert tool_msg["role"] == "user"
        assert tool_msg["content"][0]["type"] == "tool_result"
        assert tool_msg["content"][0]["tool_use_id"] == "tc1"

    def test_consecutive_tool_results_merged(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": "tc1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "tc2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "r1"},
            {"role": "tool", "tool_call_id": "tc2", "content": "r2"},
        ]
        _, converted = self.client._to_anthropic_messages(messages)
        # Both tool results should be in a single user message
        tool_msg = converted[2]
        assert tool_msg["role"] == "user"
        assert len(tool_msg["content"]) == 2

    def test_tool_definitions_converted(self):
        openai_tools = [{"type": "function", "function": {
            "name": "search", "description": "Search stuff",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }}]
        anthropic_tools = self.client._to_anthropic_tools(openai_tools)
        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["name"] == "search"
        assert "input_schema" in anthropic_tools[0]
        assert "parameters" not in anthropic_tools[0]

    def test_response_text_normalized(self):
        anthropic_resp = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        normalized = self.client._from_anthropic_response(anthropic_resp)
        msg = normalized["choices"][0]["message"]
        assert msg["content"] == "Hello world"
        assert msg["role"] == "assistant"
        assert normalized["choices"][0]["finish_reason"] == "stop"

    def test_response_tool_use_normalized(self):
        anthropic_resp = {
            "content": [
                {"type": "text", "text": "Let me search."},
                {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "test"}},
            ],
            "stop_reason": "tool_use",
        }
        normalized = self.client._from_anthropic_response(anthropic_resp)
        msg = normalized["choices"][0]["message"]
        assert msg["tool_calls"][0]["id"] == "tu_1"
        assert msg["tool_calls"][0]["function"]["name"] == "search"
        assert msg["tool_calls"][0]["function"]["arguments"] == '{"q": "test"}'
        assert normalized["choices"][0]["finish_reason"] == "tool_calls"
