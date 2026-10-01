import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from cache_cli.main import main
from caching_service.api.app import create_app
from caching_service.api.dependencies import get_session_factory, get_transformer
from caching_service.core.config import get_settings
from tests.fakes import CountingTransformerClient
from tests.integration.database import set_postgres_env, truncate_tables
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


def test_cli_repeats_against_the_real_app(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    set_postgres_env(monkeypatch, postgres_url)
    get_settings.cache_clear()
    truncate_tables(postgres_url)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    transformer = CountingTransformerClient()
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(engine, expire_on_commit=False)
    app.dependency_overrides[get_transformer] = lambda: transformer
    stdout, stderr = io.StringIO(), io.StringIO()

    try:
        code = main(
            ["-j", json.dumps(SAMPLE_REQUEST), "-r", "3"],
            stdin=io.StringIO(),
            stdout=stdout,
            stderr=stderr,
            http_client_factory=lambda _settings: TestClient(app),
        )
    finally:
        get_settings.cache_clear()

    assert code == 0, stderr.getvalue()
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["created"] for line in lines] == [True, False, False]
    assert len({line["id"] for line in lines}) == 1
    assert {line["output"] for line in lines} == {SAMPLE_OUTPUT}
    assert len(transformer.calls) == 6
