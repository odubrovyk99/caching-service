from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from caching_service.api.app import create_app
from caching_service.api.dependencies import get_session_factory, get_transformer
from tests.fakes import CountingTransformerClient


@pytest.fixture
def transformer() -> CountingTransformerClient:
    return CountingTransformerClient()


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession], transformer: CountingTransformerClient) -> FastAPI:
    # ASGITransport does not run the lifespan, so both lifespan-provided dependencies are overridden.
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_transformer] = lambda: transformer
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        yield client
