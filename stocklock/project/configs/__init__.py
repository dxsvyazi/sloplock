from pydantic_settings import BaseSettings, SettingsConfigDict


class CustomBaseSettings(BaseSettings):
  model_config = SettingsConfigDict(env_file=".env", strict=False, extra="ignore")
