"""Application settings loaded from environment variables and ``.env``.

The settings object is the single source of truth for runtime configuration.
A subset of fields is whitelisted via :data:`Settings.UPDATABLE_FIELDS` so
the ``/api/config`` route can mutate them at runtime without restarting.
"""

from typing import ClassVar

from pydantic_settings import BaseSettings

from backend.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Typed configuration for the Ops Triage Agent.

    All fields can be overridden via environment variables or a ``.env`` file
    (see :attr:`model_config`). Required values that are still set to their
    placeholder default are caught by :meth:`validate_required` at startup.

    Attributes:
        LLM_PROVIDER: LLM backend to use. Either ``anthropic`` or ``openai``.
        LLM_MODEL: Provider-specific model name.
        LLM_API_KEY: Provider API key. Must be overridden from the placeholder.
        LLM_API_BASE: Optional override for the LLM HTTP base URL.
        LLM_TIMEOUT: Per-request HTTP timeout in seconds.
        LLM_MAX_RETRIES: Maximum retry attempts for transient LLM failures.
        OPS_AGENT_API_KEY: Legacy API key. Retained for compatibility; the
            current build does not enforce it.
        ALERT_INTERVAL_MIN: Minimum seconds between simulated alerts.
        ALERT_INTERVAL_MAX: Maximum seconds between simulated alerts.
        SCENARIO_PROBABILITY: Probability (0-1) that an interval triggers a
            multi-step failure scenario instead of an isolated alert.
        DATABASE_PATH: Filesystem path to the SQLite database file.
        CHROMA_PATH: Filesystem path to the Chroma vector store directory.
        WEBHOOK_URL: Optional outbound webhook URL for escalations.
        WEBHOOK_SECRET: HMAC-SHA256 secret used to sign webhook payloads.
        WEBHOOK_MAX_RETRIES: Maximum delivery attempts before DLQ.
        TRIAGE_MAX_STEPS: Maximum tool-use iterations per triage cycle.
        TRIAGE_CONCURRENCY: Maximum concurrent triages (semaphore size).
        ALERT_QUERY_LIMIT: Row cap for ``query_recent_alerts``.
        DEFAULT_TEAM: Default team assigned to a new incident.
        SSE_HISTORY_MAX_ALERTS: Cap on retained per-alert triage histories.
        SSE_HISTORY_TTL_SECONDS: TTL for retained per-alert triage histories.
        UPDATABLE_FIELDS: Whitelist of fields the ``/api/config`` route is
            allowed to mutate at runtime, with their expected types.
    """

    LLM_PROVIDER: str = "anthropic"  # "anthropic" or "openai"
    LLM_MODEL: str = "claude-sonnet-4-6-latest"
    LLM_API_KEY: str = "your-api-key-here"
    LLM_API_BASE: str = ""
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 5
    OPS_AGENT_API_KEY: str = "demo-key-change-me"
    ALERT_INTERVAL_MIN: int = 60
    ALERT_INTERVAL_MAX: int = 100
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
        """Validates that required settings have been overridden from defaults.

        Raises:
            ConfigurationError: If ``LLM_API_KEY`` is still set to the
                placeholder value, meaning no real key was provided.
        """
        if self.LLM_API_KEY == "your-api-key-here":
            raise ConfigurationError(
                "LLM_API_KEY is not set (still using placeholder) — set it in .env or environment"
            )


settings = Settings()
