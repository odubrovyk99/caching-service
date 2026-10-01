from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from caching_service.clients.transformer_client import UppercaseTransformerClient
from caching_service.core.config import get_settings
from caching_service.core.db import create_engine, create_session_factory
from caching_service.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Configure logging, create runtime dependencies once per process, and release them on shutdown.

    Args:
        app: The application being started.

    Yields:
        Lifespan state, exposed to dependencies as ``request.state``.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    try:
        yield {"session_factory": create_session_factory(engine), "transformer": UppercaseTransformerClient()}
    finally:
        await engine.dispose()
