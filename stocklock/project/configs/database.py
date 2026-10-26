from pydantic import SecretStr

from stocklock.project.configs import CustomBaseSettings


class DatabaseSettings(CustomBaseSettings):
  STOCKLOCK_DATABASE_URL: SecretStr
