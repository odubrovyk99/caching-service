from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Body returned by ``GET /health``.

    Attributes:
        status: Always ``"ok"`` while the process serves requests.
    """

    status: str
