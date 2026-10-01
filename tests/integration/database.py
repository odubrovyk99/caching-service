import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, make_url, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from caching_service.db.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]

type AlembicCommand = Callable[[Config, str], None]


def _in_worker_thread[T](function: Callable[[], T]) -> T:
    # Alembic's async env.py and these helpers call asyncio.run, which replaces and then clears the
    # calling thread's event loop. A worker thread keeps that away from pytest-asyncio's loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(function).result()


def _migrate_on_connection(connection: Connection, alembic_command: AlembicCommand, revision: str) -> None:
    # env.py migrates on a connection passed in config.attributes instead of building its own engine.
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    alembic_command(config, revision)


def _run_alembic(database_url: str, alembic_command: AlembicCommand, revision: str) -> None:
    async def _run() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.run_sync(_migrate_on_connection, alembic_command, revision)
        await engine.dispose()

    _in_worker_thread(lambda: asyncio.run(_run()))


def upgrade_to_head(database_url: str) -> None:
    _run_alembic(database_url, command.upgrade, "head")


def downgrade_to_base(database_url: str) -> None:
    _run_alembic(database_url, command.downgrade, "base")


def _fetch_names(database_url: str, query: str) -> set[str]:
    async def _fetch() -> set[str]:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            names = set((await connection.execute(text(query))).scalars())
        await engine.dispose()
        return names

    return _in_worker_thread(lambda: asyncio.run(_fetch()))


def fetch_table_names(database_url: str) -> set[str]:
    return _fetch_names(database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")


def fetch_unique_index_names(database_url: str) -> set[str]:
    return _fetch_names(
        database_url,
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE 'CREATE UNIQUE INDEX%'",
    )


def truncate_tables(database_url: str) -> None:
    async def _truncate() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE transformation, payload"))
        await engine.dispose()

    _in_worker_thread(lambda: asyncio.run(_truncate()))


async def count_rows(engine: AsyncEngine, model: type[Base]) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(model)) or 0)


def set_postgres_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    # Points Settings (POSTGRES_* variables) at the test container, for tests that run the real lifespan.
    url = make_url(database_url)
    monkeypatch.setenv("POSTGRES_HOST", str(url.host))
    monkeypatch.setenv("POSTGRES_PORT", str(url.port))
    monkeypatch.setenv("POSTGRES_USER", str(url.username))
    monkeypatch.setenv("POSTGRES_PASSWORD", str(url.password))
    monkeypatch.setenv("POSTGRES_DB", str(url.database))
