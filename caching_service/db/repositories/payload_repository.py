from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.models import PayloadModel


class PayloadRepository:
    """Read and write generated payloads.

    Args:
        session: Request-scoped session. The caller owns commit and rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_id_by_input_hash(self, input_hash: str) -> UUID | None:
        """Find the payload generated for an input.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.

        Returns:
            The payload id, or ``None`` if this input was never stored.
        """
        result = await self._session.execute(select(PayloadModel.id).where(PayloadModel.input_hash == input_hash))
        return result.scalar_one_or_none()

    async def get_output_by_id(self, payload_id: UUID) -> str | None:
        """Read a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The stored output, or ``None`` if no payload has this id.
        """
        result = await self._session.execute(select(PayloadModel.output).where(PayloadModel.id == payload_id))
        return result.scalar_one_or_none()

    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        """Insert a payload unless one with the same input already exists.

        Args:
            payload_id: Identifier to use if the row is inserted.
            input_hash: ``payload_input_hash`` of the request lists.
            output: Final interleaved string.

        Returns:
            ``True`` if this call inserted the row, ``False`` if a row with ``input_hash`` already existed.
        """
        statement = (
            insert(PayloadModel)
            .values(id=payload_id, input_hash=input_hash, output=output)
            .on_conflict_do_nothing(index_elements=[PayloadModel.input_hash])
            .returning(PayloadModel.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None
