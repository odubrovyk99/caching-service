from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, DateTime, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from caching_service.db.models.base import Base


class PayloadModel(Base):
    """One generated payload per distinct ``(list_1, list_2)`` input.

    Attributes:
        id: Public identifier returned to clients (uuid4, generated in the app).
        input_hash: ``payload_input_hash(list_1, list_2)``; unique, used for id reuse.
        output: Final interleaved string.
        created_at: Insert time.
    """

    __tablename__ = "payload"
    __table_args__ = (Index("idx_payload__input_hash", "input_hash", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
