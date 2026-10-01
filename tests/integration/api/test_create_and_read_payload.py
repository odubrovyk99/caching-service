from http import HTTPStatus
from uuid import UUID, uuid4

import httpx2
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_STRING_LENGTH, PAYLOAD_CREATED_MESSAGE, PAYLOAD_EXISTS_MESSAGE
from caching_service.db.models import PayloadModel, TransformationModel
from tests.fakes import CountingTransformerClient
from tests.integration.database import count_rows
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


async def _create_and_read(client: httpx2.AsyncClient, body: dict[str, list[str]]) -> str:
    created = await client.post("/payload", json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    fetched = await client.get(f"/payload/{created.json()['id']}")
    assert fetched.status_code == HTTPStatus.OK
    return str(fetched.json()["output"])


async def test_sample_input_is_created_and_read_back(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient
) -> None:
    created = await client.post("/payload", json=SAMPLE_REQUEST)

    assert created.status_code == HTTPStatus.CREATED
    assert created.json()["message"] == PAYLOAD_CREATED_MESSAGE
    payload_id = UUID(created.json()["id"])
    fetched = await client.get(f"/payload/{payload_id}")
    assert fetched.status_code == HTTPStatus.OK
    assert fetched.json() == {"output": SAMPLE_OUTPUT}
    assert len(transformer.calls) == 6


async def test_repeated_input_returns_the_same_id_without_new_work(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient, engine: AsyncEngine
) -> None:
    first = await client.post("/payload", json=SAMPLE_REQUEST)
    calls_after_first = len(transformer.calls)

    second = await client.post("/payload", json=SAMPLE_REQUEST)

    assert second.status_code == HTTPStatus.OK
    assert second.json() == {"id": first.json()["id"], "message": PAYLOAD_EXISTS_MESSAGE}
    assert len(transformer.calls) == calls_after_first
    assert await count_rows(engine, PayloadModel) == 1
    assert await count_rows(engine, TransformationModel) == 6


async def test_strings_cached_by_an_earlier_request_are_not_transformed_again(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient
) -> None:
    await client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c", "d"]})
    transformer.calls.clear()

    output = await _create_and_read(client, {"list_1": ["a", "x"], "list_2": ["c", "y"]})

    assert sorted(transformer.calls) == ["x", "y"]
    assert output == "A, C, X, Y"


async def test_cached_empty_string_is_not_transformed_again(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient
) -> None:
    await client.post("/payload", json={"list_1": [""], "list_2": ["a"]})
    transformer.calls.clear()

    await client.post("/payload", json={"list_1": [""], "list_2": ["b"]})

    assert transformer.calls == ["b"]


async def test_duplicates_in_one_cold_request_are_transformed_once(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient
) -> None:
    output = await _create_and_read(client, {"list_1": ["a", "a"], "list_2": ["a", "b"]})

    assert transformer.calls == ["a", "b"]
    assert output == "A, A, A, B"


async def test_swapped_lists_are_a_different_payload(client: httpx2.AsyncClient) -> None:
    first = await client.post("/payload", json={"list_1": ["a"], "list_2": ["b"]})
    second = await client.post("/payload", json={"list_1": ["b"], "list_2": ["a"]})

    assert second.status_code == HTTPStatus.CREATED
    assert second.json()["id"] != first.json()["id"]


async def test_empty_string_item_produces_a_leading_separator(client: httpx2.AsyncClient) -> None:
    assert await _create_and_read(client, {"list_1": [""], "list_2": ["a"]}) == ", A"


async def test_unicode_long_and_separator_strings_round_trip(client: httpx2.AsyncClient) -> None:
    long_value = "x" * MAX_STRING_LENGTH
    body = {"list_1": ["straße", long_value], "list_2": ["héllo 👋", "a, b"]}

    output = await _create_and_read(client, body)

    assert output == f"STRASSE, HÉLLO 👋, {long_value.upper()}, A, B"


async def test_unknown_id_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/payload/{uuid4()}")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": "Payload not found"}


async def test_malformed_id_returns_422(client: httpx2.AsyncClient) -> None:
    response = await client.get("/payload/not-a-uuid")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_health(client: httpx2.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}
