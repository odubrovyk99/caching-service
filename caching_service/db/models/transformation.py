from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, Identity, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from caching_service.db.models.base import Base


class TransformationModel(Base):
    """One cached transformer result per distinct input string.

    Attributes:
        id: Auto-incrementing row number.
        input_hash: ``sha256_hex(input_value)``; unique, used for lookups and ``ON CONFLICT``.
        input_value: The original string, kept for debugging.
        output_value: The transformer's result.
        created_at: Insert time.
    """

    __tablename__ = "transformation"
    __table_args__ = (Index("idx_transformation__input_hash", "input_hash", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    input_value: Mapped[str] = mapped_column(Text, nullable=False)
    output_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
