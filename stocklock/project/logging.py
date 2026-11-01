"""One logging configuration for API servers and separately launched workers."""

from logging.config import dictConfig

from stocklock.project.configs.logging import LoggingSettings


def logging_config(role: str) -> dict:
  settings = LoggingSettings()
  return {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"safe": {"()": "stocklock.shared.logging.SafeFormatter", "format": settings.LOG_FORMAT}},
    "filters": {"context": {"()": "stocklock.shared.logging.LogContextFilter", "role": role}},
    "handlers": {
      "console": {
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stdout",
        "formatter": "safe",
        "filters": ["context"],
      }
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
      "stocklock": {"handlers": [], "level": settings.LOG_LEVEL, "propagate": True},
      "uvicorn": {"handlers": [], "level": settings.LOG_LEVEL, "propagate": True},
      "uvicorn.error": {"handlers": [], "level": "NOTSET", "propagate": True},
      "uvicorn.access": {"handlers": [], "level": "CRITICAL", "propagate": False},
      "sqlalchemy": {"handlers": [], "level": "WARNING", "propagate": True},
    },
  }


def configure_logging(role: str) -> None:
  dictConfig(logging_config(role))
