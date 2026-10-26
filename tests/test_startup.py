import importlib
from unittest.mock import Mock

import pytest


@pytest.fixture
def startup(monkeypatch, tmp_path):
  # Never load the developer's local dotenv file during startup tests.
  monkeypatch.chdir(tmp_path)
  monkeypatch.setenv("SERVICE_HOST", "127.0.0.1")
  monkeypatch.setenv("SERVICE_PORT", "8000")
  monkeypatch.setenv("SERVICE_SSL", "false")
  module = importlib.import_module("main")
  run = Mock()
  monkeypatch.setattr(module.uvicorn, "run", run)
  monkeypatch.setattr(module.uvicorn, "Server", Mock())
  return module, run


@pytest.mark.parametrize("reload", [False, True])
def test_main_loads_current_launch_settings(startup, monkeypatch, reload):
  module, run = startup
  monkeypatch.setenv("SERVICE_HOST", "192.0.2.10")
  monkeypatch.setenv("SERVICE_PORT", "8081")
  monkeypatch.setenv("SERVICE_RELOAD", str(reload).lower())

  module.main()

  run.assert_called_once_with(
    "stocklock.bootstrap:create_app",
    host="192.0.2.10",
    port=8081,
    factory=True,
    reload=reload,
  )


def test_service_launch_defaults(startup, monkeypatch):
  from stocklock.project.configs.service import ServiceSettings

  for name in ("SERVICE_HOST", "SERVICE_PORT", "SERVICE_SSL", "SERVICE_RELOAD"):
    monkeypatch.delenv(name, raising=False)

  settings = ServiceSettings(_env_file=None)

  assert settings.SERVICE_HOST == "0.0.0.0"
  assert settings.SERVICE_PORT == 8000
  assert settings.SERVICE_RELOAD is False
  assert settings.SERVICE_SSL is False
