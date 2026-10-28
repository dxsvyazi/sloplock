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


async def test_retention_migration_grants_existing_terminal_rows_a_full_window(database):
  from uuid import uuid4
  from sqlalchemy import text

  product_id = uuid4()
  active_id, terminal_id = uuid4(), uuid4()

  def check(connection):
    BaseORM.metadata.drop_all(connection)
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "0002_reservation_keys")
    connection.execute(
      text("INSERT INTO products (id, name, sku, stock_quantity) VALUES (:id, 'Widget', 'legacy', 7)"),
      {"id": product_id},
    )
    for id, status in ((active_id, 1), (terminal_id, 4)):
      connection.execute(
        text(
          "INSERT INTO reservations (id, product_id, quantity, status, key, created_at, expires_at) "
          "VALUES (:id, :product, 1, :status, :key, now() - interval '100 days', "
          "now() - interval '99 days')"
        ),
        {"id": id, "product": product_id, "status": status, "key": str(id)},
      )
    before = connection.scalar(text("SELECT clock_timestamp()"))
    command.upgrade(config, "head")
    after = connection.scalar(text("SELECT clock_timestamp()"))
    rows = dict(connection.execute(text("SELECT id, finalized_at FROM reservations")).all())
    assert rows[active_id] is None
    assert before <= rows[terminal_id] <= after
    command.downgrade(config, "0002_reservation_keys")
    assert connection.scalar(text("SELECT count(*) FROM reservations")) == 2
    assert "finalized_at" not in {column["name"] for column in inspect(connection).get_columns("reservations")}

  async with database.engine.begin() as connection:
    await connection.run_sync(check)
