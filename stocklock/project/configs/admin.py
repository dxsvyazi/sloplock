from pydantic import SecretStr

from stocklock.project.configs import CustomBaseSettings


class AdminSettings(CustomBaseSettings):
  ADMIN_API_TOKEN: SecretStr | None = None
