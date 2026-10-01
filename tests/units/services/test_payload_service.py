from uuid import UUID, uuid4

import pytest

from caching_service.services.payload_service import PayloadService
from tests.fakes import InMemoryPayloadRepository

INPUT_HASH = "a" * 64


class _ConflictWithoutVisibleRow(InMemoryPayloadRepository):
    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        return False


async def test_create_returns_a_new_id_when_the_insert_wins() -> None:
    repository = InMemoryPayloadRepository()

    result = await PayloadService(repository).create(INPUT_HASH, "OUT")

    assert result.created is True
    assert repository.ids_by_hash[INPUT_HASH] == result.payload_id


async def test_create_returns_the_existing_id_when_the_insert_loses() -> None:
    repository = InMemoryPayloadRepository()
    existing_id = uuid4()
    repository.ids_by_hash[INPUT_HASH] = existing_id

    result = await PayloadService(repository).create(INPUT_HASH, "OUT")

    assert result.created is False
    assert result.payload_id == existing_id


async def test_create_raises_when_the_conflicting_row_is_not_visible() -> None:
    service = PayloadService(_ConflictWithoutVisibleRow())

    with pytest.raises(RuntimeError):
        await service.create(INPUT_HASH, "OUT")
