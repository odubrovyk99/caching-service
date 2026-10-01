import asyncio
from http import HTTPStatus

import httpx2
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.db.models import PayloadModel
from tests.integration.database import count_rows
from tests.samples import SAMPLE_REQUEST


async def test_concurrent_identical_posts_converge_on_one_payload(
    client: httpx2.AsyncClient, engine: AsyncEngine
) -> None:
    responses = await asyncio.gather(*(client.post("/payload", json=SAMPLE_REQUEST) for _ in range(5)))

    assert {response.status_code for response in responses} <= {HTTPStatus.CREATED, HTTPStatus.OK}
    assert len({response.json()["id"] for response in responses}) == 1
    assert await count_rows(engine, PayloadModel) == 1


async def test_overlapping_requests_in_opposite_order_do_not_deadlock(client: httpx2.AsyncClient) -> None:
    for round_number in range(10):
        values = [f"r{round_number}-v{index}" for index in range(100)]
        reversed_values = values[::-1]
        forward = {"list_1": values[:50], "list_2": values[50:]}
        backward = {"list_1": reversed_values[:50], "list_2": reversed_values[50:]}

        responses = await asyncio.gather(client.post("/payload", json=forward), client.post("/payload", json=backward))

        assert [response.status_code for response in responses] == [HTTPStatus.CREATED, HTTPStatus.CREATED]
