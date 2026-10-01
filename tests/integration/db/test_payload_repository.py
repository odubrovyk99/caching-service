from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.repositories.payload_repository import PayloadRepository

INPUT_HASH = "a" * 64
OTHER_HASH = "b" * 64


async def test_insert_if_absent_inserts_only_the_first_time(session: AsyncSession) -> None:
    repository = PayloadRepository(session)

    first = await repository.insert_if_absent(uuid4(), INPUT_HASH, "OUT")
    second = await repository.insert_if_absent(uuid4(), INPUT_HASH, "OTHER")

    assert first is True
    assert second is False


async def test_lookups_return_stored_values_or_none(session: AsyncSession) -> None:
    repository = PayloadRepository(session)
    payload_id = uuid4()
    await repository.insert_if_absent(payload_id, INPUT_HASH, "OUT")
    await session.commit()

    assert await repository.get_id_by_input_hash(INPUT_HASH) == payload_id
    assert await repository.get_output_by_id(payload_id) == "OUT"
    assert await repository.get_id_by_input_hash(OTHER_HASH) is None
    assert await repository.get_output_by_id(uuid4()) is None
