import pytest
from backend.config import Settings
from backend.exceptions import ConfigurationError


class TestConfigValidation:
    def test_validate_required_raises_on_placeholder_llm_key(self):
        s = Settings(LLM_API_KEY="your-api-key-here", OPS_AGENT_API_KEY="real-key")
        with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
            s.validate_required()

    def test_demo_api_key_does_not_raise(self):
        """OPS_AGENT_API_KEY with demo default is a warning, not an error."""
        s = Settings(LLM_API_KEY="real-key", OPS_AGENT_API_KEY="demo-key-change-me")
        s.validate_required()  # should not raise

    def test_validate_required_passes_with_real_keys(self):
        s = Settings(LLM_API_KEY="sk-real-key", OPS_AGENT_API_KEY="prod-api-key-123")
        s.validate_required()  # should not raise

    def test_updatable_fields_types(self):
        assert Settings.UPDATABLE_FIELDS["ALERT_INTERVAL_MIN"] is int
        assert Settings.UPDATABLE_FIELDS["SCENARIO_PROBABILITY"] is float
        assert Settings.UPDATABLE_FIELDS["WEBHOOK_URL"] is str

    def test_new_config_fields_have_defaults(self):
        s = Settings(LLM_API_KEY="k", OPS_AGENT_API_KEY="k")
        assert s.TRIAGE_MAX_STEPS == 8
        assert s.TRIAGE_CONCURRENCY == 2
        assert s.LLM_TIMEOUT == 120
        assert s.LLM_MAX_RETRIES == 5
        assert s.ALERT_QUERY_LIMIT == 20
        assert s.DEFAULT_TEAM == "dc-ops-tokyo"
        assert s.WEBHOOK_MAX_RETRIES == 3
        assert s.SSE_HISTORY_MAX_ALERTS == 500
        assert s.SSE_HISTORY_TTL_SECONDS == 3600
