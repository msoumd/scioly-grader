from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scioly.db"
    tournament_pin: str = "change-me"
    upload_dir: str = "./data/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
