from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://breakmyapi:breakmyapi@localhost:5433/breakmyapi"
    cors_origins: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"

    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_model_strong: str = "openai/gpt-oss-120b"

    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Safety rule: only these origins may be scanned (comma-separated), until ownership checks exist.
    allowed_targets: str = "http://localhost:8001,http://127.0.0.1:8001"

    # Against password guessing: login attempts per 15 minutes, per email and per IP address.
    login_window_seconds: int = 15 * 60
    login_attempts_per_email: int = 10
    login_attempts_per_ip: int = 30
    signups_per_ip_per_hour: int = 5          # against mass fake accounts
    verifies_per_user_per_hour: int = 10      # each verify makes OUR server send a request

    ask_daily_limit: int = 30  # questions per client per day on POST /library/ask (each one is an LLM call)


@lru_cache
def get_settings() -> Settings:
    return Settings()
