from collections.abc import Collection, Sequence
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.models import TransformationModel
from caching_service.schemas.transformation import TransformationRecord


class TransformationRepository:
    """Read and write cached transformer results.

    Args:
        session: Request-scoped session. The caller owns commit and rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_outputs_by_hashes(self, input_hashes: Collection[str]) -> dict[str, str]:
        """Fetch cached outputs for many inputs in one query.

        Args:
            input_hashes: ``sha256_hex`` keys to look up.

        Returns:
            Mapping of input hash to cached output. Hashes with no cached row are absent.
        """
        if not input_hashes:
            return {}
        statement = select(TransformationModel.input_hash, TransformationModel.output_value).where(
            TransformationModel.input_hash.in_(list(input_hashes))
        )
        result = await self._session.execute(statement)
        return {row.input_hash: row.output_value for row in result}

    async def save_many(self, records: Sequence[TransformationRecord]) -> None:
        """Insert transformer results in one statement, skipping inputs that are already cached.

        Rows are inserted in ``input_hash`` order so that concurrent transactions with overlapping inputs
        take row locks in the same order and cannot deadlock each other.

        Args:
            records: Results to cache. Must not contain duplicate hashes.
        """
        if not records:
            return
        rows = [asdict(record) for record in sorted(records, key=lambda record: record.input_hash)]
        statement = (
            insert(TransformationModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[TransformationModel.input_hash])
        )
        await self._session.execute(statement)
