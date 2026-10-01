import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from caching_service.constants import MAX_STRING_LENGTH
from caching_service.db.models import TransformationModel
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.schemas.transformation import TransformationRecord
from caching_service.utils.hashing import sha256_hex
from tests.integration.database import count_rows


def _record(value: str, output: str | None = None) -> TransformationRecord:
    return TransformationRecord(
        input_hash=sha256_hex(value),
        input_value=value,
        output_value=value.upper() if output is None else output,
    )


async def _save_and_commit(session: AsyncSession, records: list[TransformationRecord]) -> None:
    await TransformationRepository(session).save_many(records)
    await session.commit()


async def test_saved_records_are_returned_by_hash(session: AsyncSession) -> None:
    repository = TransformationRepository(session)
    await repository.save_many([_record("a"), _record("b")])
    await session.commit()

    outputs = await repository.get_outputs_by_hashes([sha256_hex("a"), sha256_hex("b"), sha256_hex("missing")])

    assert outputs == {sha256_hex("a"): "A", sha256_hex("b"): "B"}


async def test_lookup_without_hashes_returns_an_empty_mapping(session: AsyncSession) -> None:
    assert await TransformationRepository(session).get_outputs_by_hashes([]) == {}


async def test_saving_an_existing_hash_keeps_the_original_row(session: AsyncSession) -> None:
    repository = TransformationRepository(session)
    await repository.save_many([_record("a", "first")])
    await session.commit()

    await repository.save_many([_record("a", "second")])
    await session.commit()

    assert await repository.get_outputs_by_hashes([sha256_hex("a")]) == {sha256_hex("a"): "first"}


async def test_values_longer_than_a_btree_entry_round_trip(session: AsyncSession) -> None:
    value = "x" * MAX_STRING_LENGTH
    repository = TransformationRepository(session)
    await repository.save_many([_record(value)])
    await session.commit()

    assert await repository.get_outputs_by_hashes([sha256_hex(value)]) == {sha256_hex(value): value.upper()}


async def test_concurrent_sessions_inserting_the_same_hash_keep_one_row(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as first, session_factory() as second:
        await TransformationRepository(first).save_many([_record("a")])
        second_insert = asyncio.create_task(_save_and_commit(second, [_record("a")]))
        await asyncio.sleep(0.2)  # lets the second insert block on the first session's uncommitted row
        await first.commit()
        await second_insert

    assert await count_rows(engine, TransformationModel) == 1
