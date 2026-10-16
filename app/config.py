from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field("sqlite:///./stellartrack.db", alias="DATABASE_URL")
    secret_key: str = Field("development-only-change-me", alias="SECRET_KEY")
    environment: str = Field("development", alias="ENVIRONMENT")
    app_timezone: str = Field("Asia/Kolkata", alias="APP_TIMEZONE")
    secure_cookies: bool = Field(False, alias="SECURE_COOKIES")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
