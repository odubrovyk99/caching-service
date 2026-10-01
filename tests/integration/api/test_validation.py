import json
from http import HTTPStatus

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_LIST_LENGTH
from caching_service.db.models import PayloadModel, TransformationModel
from tests.fakes import CountingTransformerClient
from tests.integration.database import count_rows

INVALID_BODIES = {
    "unequal_lengths": json.dumps({"list_1": ["a", "b"], "list_2": ["c"]}),
    "empty_lists": json.dumps({"list_1": [], "list_2": []}),
    "integer_item": json.dumps({"list_1": [123], "list_2": ["a"]}),
    "extra_key": json.dumps({"list_1": ["a"], "list_2": ["b"], "list_3": ["c"]}),
    "missing_key": json.dumps({"list_1": ["a"]}),
    "array_body": json.dumps([["a"], ["b"]]),
    "nul_character": json.dumps({"list_1": ["a\x00b"], "list_2": ["c"]}),
    "lone_surrogate": '{"list_1": ["\\ud800"], "list_2": ["c"]}',
    "too_many_items": json.dumps({"list_1": ["a"] * (MAX_LIST_LENGTH + 1), "list_2": ["b"] * (MAX_LIST_LENGTH + 1)}),
}


@pytest.mark.parametrize("raw_body", list(INVALID_BODIES.values()), ids=list(INVALID_BODIES))
async def test_invalid_bodies_are_rejected_without_side_effects(
    client: httpx2.AsyncClient, transformer: CountingTransformerClient, engine: AsyncEngine, raw_body: str
) -> None:
    response = await client.post(
        "/payload", content=raw_body.encode("utf-8"), headers={"content-type": "application/json"}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert transformer.calls == []
    assert await count_rows(engine, PayloadModel) == 0
    assert await count_rows(engine, TransformationModel) == 0


async def test_unequal_lengths_error_names_the_rule(client: httpx2.AsyncClient) -> None:
    response = await client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c"]})

    assert "list_1 and list_2 must have the same length" in response.text
