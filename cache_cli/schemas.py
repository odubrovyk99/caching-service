from uuid import UUID

from pydantic import BaseModel


class IterationResult(BaseModel):
    """One output line of ``cache-cli``: the outcome of one POST+GET iteration.

    Attributes:
        iteration: 1-based iteration number.
        id: Payload identifier returned by ``POST /payload``.
        created: ``True`` if this iteration created the payload, ``False`` if it already existed.
        output: Payload output returned by ``GET /payload/{id}``.
    """

    iteration: int
    id: UUID
    created: bool
    output: str
