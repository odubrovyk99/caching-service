from collections.abc import Collection, Sequence
from uuid import UUID

from caching_service.schemas.transformation import TransformationRecord


class CountingTransformerClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def transform(self, value: str) -> str:
        self.calls.append(value)
        return value.upper()


class InMemoryTransformationRepository:
    def __init__(self, outputs_by_hash: dict[str, str] | None = None) -> None:
        self.outputs_by_hash = dict(outputs_by_hash or {})
        self.saved: list[TransformationRecord] = []

    async def get_outputs_by_hashes(self, input_hashes: Collection[str]) -> dict[str, str]:
        return {key: self.outputs_by_hash[key] for key in input_hashes if key in self.outputs_by_hash}

    async def save_many(self, records: Sequence[TransformationRecord]) -> None:
        self.saved.extend(records)
        for record in records:
            self.outputs_by_hash.setdefault(record.input_hash, record.output_value)


class InMemoryPayloadRepository:
    def __init__(self) -> None:
        self.ids_by_hash: dict[str, UUID] = {}
        self.outputs_by_id: dict[UUID, str] = {}

    async def get_id_by_input_hash(self, input_hash: str) -> UUID | None:
        return self.ids_by_hash.get(input_hash)

    async def get_output_by_id(self, payload_id: UUID) -> str | None:
        return self.outputs_by_id.get(payload_id)

    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        if input_hash in self.ids_by_hash:
            return False
        self.ids_by_hash[input_hash] = payload_id
        self.outputs_by_id[payload_id] = output
        return True
