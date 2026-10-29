import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from stocklock.infrastructure.models import BaseORM
from stocklock.infrastructure.models.confirmation import ConfirmationORM  # noqa: F401
from stocklock.infrastructure.models.product import ProductORM  # noqa: F401
from stocklock.infrastructure.models.reservation import ReservationORM  # noqa: F401

config = context.config

if config.config_file_name is not None:
  fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = BaseORM.metadata


def database_url() -> str:
  url = os.environ.get("STOCKLOCK_DATABASE_URL") or config.get_main_option("sqlalchemy.url")

  assert url

  return url


def run_migrations_offline() -> None:
  context.configure(
    url=database_url(),
    target_metadata=target_metadata,
    literal_binds=True,
    dialect_opts={"paramstyle": "named"},
    compare_type=True,
  )
  with context.begin_transaction():
    context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
  context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
  with context.begin_transaction():
    context.run_migrations()


async def run_async_migrations() -> None:
  settings = config.get_section(config.config_ini_section, {})
  settings["sqlalchemy.url"] = database_url()
  engine = async_engine_from_config(settings, prefix="sqlalchemy.", poolclass=pool.NullPool)
  try:
    async with engine.connect() as connection:
      await connection.run_sync(do_run_migrations)
  finally:
    await engine.dispose()


if context.is_offline_mode():
  run_migrations_offline()
elif (connection := config.attributes.get("connection")) is not None:
  do_run_migrations(connection)
else:
  asyncio.run(run_async_migrations())
