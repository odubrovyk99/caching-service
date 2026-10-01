from fastapi import APIRouter

from caching_service.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    """Report that the process is serving requests.

    Returns:
        ``{"status": "ok"}``.
    """
    return HealthResponse(status="ok")
