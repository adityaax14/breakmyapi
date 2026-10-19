from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://breakmyapi:breakmyapi@localhost:5433/breakmyapi"
    cors_origins: str = "http://localhost:5173"

    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_model_strong: str = "openai/gpt-oss-120b"

    embedding_model: str = "BAAI/bge-small-en-v1.5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
