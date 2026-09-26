from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FoundrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: AnyHttpUrl
    ollama_model: str = Field(min_length=1)
    max_concurrency: int = Field(default=1, ge=1)
    foundry_data_dir: Path = Path("data")
    foundry_artifact_dir: Path = Path("artifacts")
    builder_a2a_url: AnyHttpUrl = AnyHttpUrl("http://builder:8001")
    runner_a2a_url: AnyHttpUrl = AnyHttpUrl("http://runner:8002")
    builder_a2a_public_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001")
    runner_a2a_public_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8002")

    @field_validator("ollama_model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("OLLAMA_MODEL must not be blank")
        return value
