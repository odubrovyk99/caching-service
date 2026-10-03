from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from caching_service.api.errors import validation_error_handler
from caching_service.api.lifespan import lifespan
from caching_service.api.routes.health import router as health_router
from caching_service.api.routes.metrics import router as metrics_router
from caching_service.api.routes.payload import router as payload_router


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        The configured application.
    """
    app = FastAPI(title="caching-service", lifespan=lifespan)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(payload_router)
    return app
