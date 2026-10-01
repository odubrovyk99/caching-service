# ruff: noqa: A005
import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logger = logging.getLogger("caching_service")


def configure_logging(level: str) -> None:
    """Send log records to stderr in one plain-text format.

    Called once from ``lifespan``, never at import time.

    Args:
        level: Standard level name, such as ``"INFO"`` or ``"DEBUG"``.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
