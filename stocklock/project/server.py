"""Container server launcher, including logging in the reload supervisor."""

import os

import uvicorn

from stocklock.project.logging import logging_config


def main() -> None:
  uvicorn.run(
    "stocklock.bootstrap:create_app",
    host="0.0.0.0",
    port=int(os.environ.get("PORT") or "8000"),
    reload=True,
    workers=int(os.environ.get("WORKERS") or "1"),
    factory=True,
    log_config=logging_config("api"),
    access_log=False,
  )


if __name__ == "__main__":
  main()
