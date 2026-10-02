from collections.abc import Iterator
from http import HTTPStatus

import httpx2

from cache_cli.schemas import IterationResult
from caching_service.schemas.payload import PayloadCreateRequest, PayloadCreateResponse, PayloadReadResponse


def run_iterations(client: httpx2.Client, request: PayloadCreateRequest, repeat: int) -> Iterator[str]:
    """POST the payload and GET it back ``repeat`` times, yielding one JSON line per iteration.

    Lines are yielded as each iteration finishes, so a later failure keeps the earlier results.

    Args:
        client: HTTP client with ``base_url`` pointing at the service.
        request: Validated request body.
        repeat: Number of iterations (≥ 1).

    Yields:
        One ``IterationResult`` serialized as a JSON line.

    Raises:
        httpx2.HTTPError: On a connection failure or a non-2xx response.
        ValueError: If a 2xx response body is not JSON or not the expected payload response.
    """
    body = request.model_dump()
    for iteration in range(1, repeat + 1):
        create_response = client.post("/payload", json=body)
        create_response.raise_for_status()
        created = PayloadCreateResponse.model_validate(create_response.json())

        read_response = client.get(f"/payload/{created.id}")
        read_response.raise_for_status()
        payload = PayloadReadResponse.model_validate(read_response.json())

        yield IterationResult(
            iteration=iteration,
            id=created.id,
            created=create_response.status_code == HTTPStatus.CREATED,
            output=payload.output,
        ).model_dump_json()
