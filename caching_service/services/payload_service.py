from uuid import UUID, uuid4

from caching_service.db.repositories.payload_repository import PayloadRepository
from caching_service.schemas.payload import PayloadCreationResult


class PayloadService:
    """Look up and store generated payloads.

    Args:
        repository: Payload storage.
    """

    def __init__(self, repository: PayloadRepository) -> None:
        self._repository = repository

    async def find_id(self, input_hash: str) -> UUID | None:
        """Find the payload already generated for an input.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.

        Returns:
            The existing payload id, or ``None``.
        """
        return await self._repository.get_id_by_input_hash(input_hash)

    async def get_output(self, payload_id: UUID) -> str | None:
        """Read a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The output, or ``None`` if the id is unknown.
        """
        return await self._repository.get_output_by_id(payload_id)

    async def create(self, input_hash: str, output: str) -> PayloadCreationResult:
        """Store a payload, or return the one a concurrent request stored first.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.
            output: Final interleaved string.

        Returns:
            The new id with ``created=True``, or the concurrent winner's id with ``created=False``.

        Raises:
            RuntimeError: If the insert conflicted but no row with that hash is visible. That would mean
                payload rows are being deleted, which this service never does.
        """
        payload_id = uuid4()
        if await self._repository.insert_if_absent(payload_id, input_hash, output):
            return PayloadCreationResult(payload_id=payload_id, created=True)

        existing_id = await self._repository.get_id_by_input_hash(input_hash)
        if existing_id is None:
            raise RuntimeError(f"Payload insert conflicted on {input_hash} but no row is visible")
        return PayloadCreationResult(payload_id=existing_id, created=False)
