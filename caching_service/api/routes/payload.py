from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from caching_service.api.dependencies import get_create_payload_use_case, get_get_payload_use_case
from caching_service.constants import PAYLOAD_CREATED_MESSAGE, PAYLOAD_EXISTS_MESSAGE, PAYLOAD_NOT_FOUND_DETAIL
from caching_service.schemas.payload import PayloadCreateRequest, PayloadCreateResponse, PayloadReadResponse
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.use_cases.get_payload import GetPayloadUseCase

router = APIRouter(prefix="/payload", tags=["payload"])


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    responses={HTTPStatus.OK: {"model": PayloadCreateResponse, "description": "Payload already exists"}},
)
async def create_payload(
    body: PayloadCreateRequest,
    response: Response,
    use_case: Annotated[CreatePayloadUseCase, Depends(get_create_payload_use_case)],
) -> PayloadCreateResponse:
    """Create a payload, or return the id of the identical payload created earlier.

    Args:
        body: The two input lists.
        response: Used to downgrade the status to 200 when the payload already existed.
        use_case: Create-payload use case.

    Returns:
        The payload id and a created/exists message.
    """
    result = await use_case.execute(body.list_1, body.list_2)
    if not result.created:
        response.status_code = HTTPStatus.OK
        return PayloadCreateResponse(id=result.payload_id, message=PAYLOAD_EXISTS_MESSAGE)
    return PayloadCreateResponse(id=result.payload_id, message=PAYLOAD_CREATED_MESSAGE)


@router.get("/{payload_id}", responses={HTTPStatus.NOT_FOUND: {"description": PAYLOAD_NOT_FOUND_DETAIL}})
async def get_payload(
    payload_id: UUID, use_case: Annotated[GetPayloadUseCase, Depends(get_get_payload_use_case)]
) -> PayloadReadResponse:
    """Return a generated payload.

    Args:
        payload_id: Identifier returned by ``POST /payload``.
        use_case: Get-payload use case.

    Returns:
        The payload output.

    Raises:
        HTTPException: 404 if no payload has this id.
    """
    output = await use_case.execute(payload_id)
    if output is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=PAYLOAD_NOT_FOUND_DETAIL)
    return PayloadReadResponse(output=output)
