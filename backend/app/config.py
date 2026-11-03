from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Отключаем защиту префикса "model_", чтобы поле model_name
        # не конфликтовало с BaseModel.model_*.
        protected_namespaces=(),
    )

    # ─── LLM ─────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o-mini"
    temperature: float = 0.3

    max_tokens: int = 24000
    llm_timeout_seconds: float = 300.0
    llm_max_retries: int = 0

    use_json_mode: bool = False
    use_critic: bool = True

    checkpoint_db: str = ":memory:"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    @field_validator("openai_base_url", "model_name")
    @classmethod
    def not_blank(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} не может быть пустым")
        return v


settings = Settings()