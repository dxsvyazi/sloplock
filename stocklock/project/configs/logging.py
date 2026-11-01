from typing import Literal

from stocklock.project.configs import CustomBaseSettings


class LoggingSettings(CustomBaseSettings):
  LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
  LOG_FORMAT: Literal["text", "json"] = "text"
