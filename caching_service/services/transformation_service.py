from collections.abc import Iterable

from caching_service.clients.transformer_client import TransformerClient
from caching_service.core.metrics import TRANSFORMER_CALLS
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.schemas.transformation import TransformationRecord
from caching_service.utils.hashing import sha256_hex


class TransformationService:
    """Transform strings through the Postgres cache, calling the transformer only on misses.

    Args:
        repository: Cache storage.
        transformer: The (expensive) transformer.
    """

    def __init__(self, repository: TransformationRepository, transformer: TransformerClient) -> None:
        self._repository = repository
        self._transformer = transformer

    async def transform_all(self, values: Iterable[str]) -> dict[str, str]:
        """Transform strings, calling the transformer only for strings never seen before.

        Duplicates are removed first: the cache is checked only once per request, so a string that appears
        several times in a new request would otherwise be sent to the transformer several times.

        Args:
            values: Strings to transform, in any order, duplicates allowed.

        Returns:
            Mapping from each distinct input string to its transformed output.
        """
        unique_values = list(dict.fromkeys(values))
        hash_by_value = {value: sha256_hex(value) for value in unique_values}
        cached_outputs = await self._repository.get_outputs_by_hashes(list(hash_by_value.values()))

        outputs: dict[str, str] = {}
        new_records: list[TransformationRecord] = []
        for value in unique_values:
            input_hash = hash_by_value[value]
            # `is None`, not falsiness: a cached empty string is a hit.
            output = cached_outputs.get(input_hash)
            if output is None:
                TRANSFORMER_CALLS.inc()
                output = await self._transformer.transform(value)
                new_records.append(TransformationRecord(input_hash=input_hash, input_value=value, output_value=output))
            outputs[value] = output

        await self._repository.save_many(new_records)
        return outputs
