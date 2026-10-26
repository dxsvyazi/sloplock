import uvicorn

from stocklock.project.configs.service import ServiceSettings


def main() -> None:
  settings = ServiceSettings()
  uvicorn.run(
    "stocklock.bootstrap:create_app",
    host=settings.SERVICE_HOST,
    port=settings.SERVICE_PORT,
    factory=True,
    reload=settings.SERVICE_RELOAD,
  )


if __name__ == "__main__":
  main()
