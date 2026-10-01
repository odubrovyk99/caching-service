from collections.abc import Sequence

from caching_service.constants import OUTPUT_SEPARATOR
from caching_service.core.logging import logger
from caching_service.schemas.payload import PayloadCreationResult
from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.utils.hashing import payload_input_hash
from caching_service.utils.interleave import interleave


class CreatePayloadUseCase:
    """Create a payload from two lists, or return the id of the identical payload created before.

    Args:
        payload_service: Payload lookup and storage.
        transformation_service: Cache-first transformer access.
    """

    def __init__(self, payload_service: PayloadService, transformation_service: TransformationService) -> None:
        self._payload_service = payload_service
        self._transformation_service = transformation_service

    async def execute(self, list_1: Sequence[str], list_2: Sequence[str]) -> PayloadCreationResult:
        """Create or reuse the payload for ``(list_1, list_2)``.

        A known input returns before any transformation lookup, so a repeated payload costs one query and
        zero transformer calls.

        Args:
            list_1: Strings for even output positions.
            list_2: Strings for odd output positions; same length as ``list_1``.

        Returns:
            The payload id and whether this call created it.
        """
        input_hash = payload_input_hash(list_1, list_2)
        existing_id = await self._payload_service.find_id(input_hash)
        if existing_id is not None:
            return PayloadCreationResult(payload_id=existing_id, created=False)

        outputs = await self._transformation_service.transform_all([*list_1, *list_2])
        ordered_outputs = interleave([outputs[value] for value in list_1], [outputs[value] for value in list_2])
        result = await self._payload_service.create(input_hash, OUTPUT_SEPARATOR.join(ordered_outputs))
        logger.info("Payload stored: payload_id=%s created=%s", result.payload_id, result.created)
        return result
