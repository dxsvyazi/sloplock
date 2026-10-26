from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from stocklock.infrastructure.models import BaseORM


async def test_migration_upgrade_matches_models_and_downgrades(database):
  def check(connection):
    BaseORM.metadata.drop_all(connection)
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    assert set(inspect(connection).get_table_names()) == {
      "products",
      "reservations",
      "confirmations",
      "alembic_version",
    }
    assert compare_metadata(MigrationContext.configure(connection), BaseORM.metadata) == []
    command.downgrade(config, "base")
    assert inspect(connection).get_table_names() == ["alembic_version"]

  async with database.engine.begin() as connection:
    await connection.run_sync(check)
