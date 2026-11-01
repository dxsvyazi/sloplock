import uvicorn

from stocklock.project.configs.service import ServiceSettings
from stocklock.project.logging import logging_config


def main() -> None:
  settings = ServiceSettings()
  uvicorn.run(
    "stocklock.bootstrap:create_app",
    host=settings.SERVICE_HOST,
    port=settings.SERVICE_PORT,
    factory=True,
    reload=settings.SERVICE_RELOAD,
    log_config=logging_config("api"),
    access_log=False,
  )


if __name__ == "__main__":
  main()
