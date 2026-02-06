from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8', extra='ignore')

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    LOG_LEVEL: str = "INFO"


settings = Settings()  # type: ignore
