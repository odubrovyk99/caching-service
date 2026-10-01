from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: URL) -> AsyncEngine:
    """Create the application's async engine.

    Args:
        database_url: ``postgresql+asyncpg`` URL built by ``Settings.database_url``.

    Returns:
        An engine with pre-ping enabled, so connections dropped by a Postgres restart are replaced
        instead of failing a request.
    """
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the per-request session factory.

    Args:
        engine: Engine created at startup.

    Returns:
        A sessionmaker with ``expire_on_commit=False``, so loaded values stay readable after commit.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
