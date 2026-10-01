from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from caching_service.api.app import create_app
from caching_service.core.config import get_settings
from tests.integration.database import set_postgres_env


def test_real_lifespan_serves_health_create_and_read(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    set_postgres_env(monkeypatch, postgres_url)
    get_settings.cache_clear()
    unique_value = f"lifespan-{uuid4()}"
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
            created = client.post("/payload", json={"list_1": [unique_value], "list_2": ["b"]})
            assert created.status_code == HTTPStatus.CREATED
            fetched = client.get(f"/payload/{created.json()['id']}")
            assert fetched.json() == {"output": f"{unique_value.upper()}, B"}
    finally:
        get_settings.cache_clear()
