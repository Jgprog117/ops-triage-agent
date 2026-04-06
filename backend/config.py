from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    LLM_PROVIDER: str = "openai"  # "openai" or "anthropic"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = "your-api-key-here"
    LLM_API_BASE: str = ""
    OPS_AGENT_API_KEY: str = "demo-key-change-me"
    ALERT_INTERVAL_MIN: int = 3
    ALERT_INTERVAL_MAX: int = 8
    SCENARIO_PROBABILITY: float = 0.3
    DATABASE_PATH: str = "data/ops_agent.db"
    CHROMA_PATH: str = "data/chroma"
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
