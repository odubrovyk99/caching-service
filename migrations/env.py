import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from caching_service.core.config import get_settings
from caching_service.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without connecting to a database."""
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_on_connection(connection: Connection) -> None:
    """Run migrations on a synchronous connection.

    Args:
        connection: Connection handed in by a caller, or the sync view of our own async connection.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_with_new_engine() -> None:
    """Run migrations on a fresh engine built from the ``POSTGRES_*`` settings."""
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations_on_connection)
    await engine.dispose()


def run_migrations_online() -> None:
    """Migrate on the connection a caller passed in ``config.attributes`` (tests), else on a new engine."""
    connection: Connection | None = config.attributes.get("connection")
    if connection is None:
        asyncio.run(_run_migrations_with_new_engine())
    else:
        _run_migrations_on_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
