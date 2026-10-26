from . import CustomBaseSettings


class ServiceSettings(CustomBaseSettings):
  SERVICE_HOST: str = "0.0.0.0"
  SERVICE_PORT: int = 8000
  SERVICE_RELOAD: bool = False
  # Describes the public URL (for example, TLS terminated by a reverse proxy).
  # TLS certificates and HTTPS listeners are configured outside these settings.
  SERVICE_SSL: bool = False

  @property
  def url(self) -> str:
    return f"{'https' if self.SERVICE_SSL else 'http'}://{self.SERVICE_HOST}:{self.SERVICE_PORT}"
