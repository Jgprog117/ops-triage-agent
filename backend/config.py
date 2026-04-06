from typing import ClassVar

from pydantic_settings import BaseSettings

from backend.exceptions import ConfigurationError


class Settings(BaseSettings):
    LLM_PROVIDER: str = "anthropic"  # "anthropic" or "openai"
    LLM_MODEL: str = "claude-sonnet-4-6-latest"
    LLM_API_KEY: str = "your-api-key-here"
    LLM_API_BASE: str = ""
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 5
    OPS_AGENT_API_KEY: str = "demo-key-change-me"
    ALERT_INTERVAL_MIN: int = 90
    ALERT_INTERVAL_MAX: int = 150
    SCENARIO_PROBABILITY: float = 0.15
    DATABASE_PATH: str = "data/ops_agent.db"
    CHROMA_PATH: str = "data/chroma"
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    WEBHOOK_MAX_RETRIES: int = 3
    TRIAGE_MAX_STEPS: int = 8
    TRIAGE_CONCURRENCY: int = 2
    ALERT_QUERY_LIMIT: int = 20
    DEFAULT_TEAM: str = "dc-ops-tokyo"
    SSE_HISTORY_MAX_ALERTS: int = 500
    SSE_HISTORY_TTL_SECONDS: int = 3600

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    UPDATABLE_FIELDS: ClassVar[dict[str, type]] = {
        "ALERT_INTERVAL_MIN": int,
        "ALERT_INTERVAL_MAX": int,
        "SCENARIO_PROBABILITY": float,
        "WEBHOOK_URL": str,
        "WEBHOOK_SECRET": str,
    }

    def validate_required(self) -> None:
        errors: list[str] = []
        if self.LLM_API_KEY == "your-api-key-here":
            errors.append("LLM_API_KEY is not set (still using placeholder)")
        if self.OPS_AGENT_API_KEY == "demo-key-change-me":
            errors.append("OPS_AGENT_API_KEY is not set (still using demo default)")
        if errors:
            raise ConfigurationError(
                "Invalid configuration — set these in .env or environment:\n  • " + "\n  • ".join(errors)
            )


settings = Settings()
