from collections.abc import Iterator
from http import HTTPStatus
from typing import Any

import httpx2
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_LIST_LENGTH
from tests.samples import SAMPLE_REQUEST

APPLICATION_TABLES = ("payload", "transformation")


@pytest.fixture
def executed_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(*args: Any) -> None:
        statement = args[2]
        # Counts only statements on our tables, so driver/dialect bookkeeping queries cannot skew the budget.
        if any(table in statement for table in APPLICATION_TABLES):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    yield statements
    event.remove(engine.sync_engine, "before_cursor_execute", _record)


async def test_new_payload_at_the_size_limit_uses_at_most_five_statements(
    client: httpx2.AsyncClient, executed_statements: list[str]
) -> None:
    body = {
        "list_1": [f"a{index}" for index in range(MAX_LIST_LENGTH)],
        "list_2": [f"b{index}" for index in range(MAX_LIST_LENGTH)],
    }

    response = await client.post("/payload", json=body)

    assert response.status_code == HTTPStatus.CREATED
    assert len(executed_statements) <= 5, executed_statements


async def test_repeated_payload_uses_exactly_one_statement(
    client: httpx2.AsyncClient, executed_statements: list[str]
) -> None:
    await client.post("/payload", json=SAMPLE_REQUEST)
    executed_statements.clear()

    response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == HTTPStatus.OK
    assert len(executed_statements) == 1, executed_statements
