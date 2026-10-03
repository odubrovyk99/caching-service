from http import HTTPStatus

import httpx2
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families

from tests.samples import SAMPLE_REQUEST


async def _transformer_calls(client: httpx2.AsyncClient) -> float:
    response = await client.get("/metrics")
    assert response.status_code == HTTPStatus.OK
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST
    for family in text_string_to_metric_families(response.text):
        for sample in family.samples:
            if sample.name == "transformer_calls_total":
                return sample.value
    raise AssertionError("transformer_calls_total is not exposed")


async def test_metrics_count_transformer_calls_not_requests(client: httpx2.AsyncClient) -> None:
    before = await _transformer_calls(client)

    await client.post("/payload", json=SAMPLE_REQUEST)
    await client.post("/payload", json=SAMPLE_REQUEST)

    assert await _transformer_calls(client) - before == 6
