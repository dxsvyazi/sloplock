import importlib
from unittest.mock import Mock

import pytest
from unittest.mock import ANY


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
    log_config=ANY,
    access_log=False,
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


def test_container_entrypoint_preserves_listener_and_reload_with_shared_logging(monkeypatch):
  from stocklock.project import server

  run = Mock()
  monkeypatch.setattr(server.uvicorn, "run", run)
  monkeypatch.setenv("PORT", "8090")
  monkeypatch.setenv("WORKERS", "3")
  server.main()
  run.assert_called_once_with(
    "stocklock.bootstrap:create_app",
    host="0.0.0.0",
    port=8090,
    reload=True,
    workers=3,
    factory=True,
    log_config=ANY,
    access_log=False,
  )
  assert run.call_args.kwargs["log_config"]["filters"]["context"]["role"] == "api"


@pytest.mark.parametrize("value", [None, ""])
def test_container_launch_defaults_match_shell_empty_variable_behavior(monkeypatch, value):
  from stocklock.project import server

  for name in ("PORT", "WORKERS"):
    if value is None:
      monkeypatch.delenv(name, raising=False)
    else:
      monkeypatch.setenv(name, value)
  run = Mock()
  monkeypatch.setattr(server.uvicorn, "run", run)
  server.main()
  assert run.call_args.kwargs["port"] == 8000
  assert run.call_args.kwargs["workers"] == 1
