"""Environment-based configuration for explicitly invoked LLM calls."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    openai_api_key: SecretStr
    openai_model: str = Field(min_length=1)
    openai_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    @field_validator("openai_api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key:
            raise ValueError("OPENAI_API_KEY must not be blank")
        return SecretStr(key)
