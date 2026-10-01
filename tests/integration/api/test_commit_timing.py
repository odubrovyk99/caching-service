from http import HTTPStatus

import httpx2
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from caching_service.api.dependencies import get_session_factory
from tests.samples import SAMPLE_REQUEST


class _FailingCommitSession(AsyncSession):
    async def commit(self) -> None:
        raise RuntimeError("simulated commit failure")


async def test_commit_failure_reaches_the_client(app: FastAPI, engine: AsyncEngine) -> None:
    failing_factory = async_sessionmaker(engine, class_=_FailingCommitSession, expire_on_commit=False)
    app.dependency_overrides[get_session_factory] = lambda: failing_factory
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    # With FastAPI's default yield-dependency scope the client would already hold a 201 here.
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
