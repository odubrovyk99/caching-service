import json
from http import HTTPStatus

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError


async def validation_error_handler(request: Request, error: RequestValidationError) -> Response:
    """Render request validation errors like FastAPI does, but safe for any input.

    FastAPI echoes the offending input back in the error body. The default renderer encodes it as UTF-8,
    which fails on a broken Unicode character (half of an emoji code sent alone, e.g. ``"\\ud800"``) and
    turns the 422 into a 500. ``ensure_ascii`` escapes every non-ASCII character, so the body always encodes.

    Args:
        request: The rejected request.
        error: The validation error.

    Returns:
        A 422 response with FastAPI's usual ``{"detail": [...]}`` body, ASCII-escaped.
    """
    body = json.dumps({"detail": jsonable_encoder(error.errors())}, ensure_ascii=True)
    return Response(content=body, status_code=HTTPStatus.UNPROCESSABLE_ENTITY, media_type="application/json")
