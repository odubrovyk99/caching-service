from uuid import UUID

from caching_service.services.payload_service import PayloadService


class GetPayloadUseCase:
    """Read a generated payload by id.

    Args:
        payload_service: Payload lookup.
    """

    def __init__(self, payload_service: PayloadService) -> None:
        self._payload_service = payload_service

    async def execute(self, payload_id: UUID) -> str | None:
        """Fetch a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The output, or ``None`` if the id is unknown.
        """
        return await self._payload_service.get_output(payload_id)
