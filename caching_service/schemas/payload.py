from dataclasses import dataclass
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, model_validator

from caching_service.constants import MAX_LIST_LENGTH, MAX_STRING_LENGTH


def _reject_nul(value: str) -> str:
    """Reject strings containing NUL, which Postgres TEXT cannot store.

    Without this a NUL would pass validation and surface as a 500 at insert time.

    Args:
        value: A single list item.

    Returns:
        The unchanged value.

    Raises:
        ValueError: If the value contains a NUL character.
    """
    if "\x00" in value:
        raise ValueError("strings must not contain NUL characters")
    return value


PayloadItem = Annotated[StrictStr, Field(max_length=MAX_STRING_LENGTH), AfterValidator(_reject_nul)]
PayloadItems = Annotated[list[PayloadItem], Field(min_length=1, max_length=MAX_LIST_LENGTH)]


class PayloadCreateRequest(BaseModel):
    """Body of ``POST /payload``.

    Attributes:
        list_1: Strings placed at even positions of the output.
        list_2: Strings placed at odd positions of the output; same length as ``list_1``.
    """

    model_config = ConfigDict(extra="forbid")

    list_1: PayloadItems
    list_2: PayloadItems

    @model_validator(mode="after")
    def _lists_have_equal_length(self) -> Self:
        """Enforce the equal-length rule that interleaving depends on.

        Returns:
            The validated model.

        Raises:
            ValueError: If the lists differ in length.
        """
        if len(self.list_1) != len(self.list_2):
            raise ValueError("list_1 and list_2 must have the same length")
        return self


class PayloadCreateResponse(BaseModel):
    """Body returned by ``POST /payload``.

    Attributes:
        id: Identifier of the created or reused payload.
        message: Whether the payload was created or already existed.
    """

    id: UUID
    message: str


class PayloadReadResponse(BaseModel):
    """Body returned by ``GET /payload/{id}``.

    Attributes:
        output: Interleaved transformed strings joined by ``", "``.
    """

    output: str


@dataclass(frozen=True, slots=True)
class PayloadCreationResult:
    """Outcome of storing a payload, before it is mapped to HTTP.

    Attributes:
        payload_id: Identifier of the created or reused payload.
        created: ``True`` if this call created the payload, ``False`` if it already existed.
    """

    payload_id: UUID
    created: bool
