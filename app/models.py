"""Database models."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for ORM models."""


class Document(Base):
    """A document; PostgreSQL is the source of truth, Elasticsearch only indexes ``id`` and ``text``."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rubrics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql_text("'{}'")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"Document(id={self.id!r}, created_date={self.created_date!r})"
