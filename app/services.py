"""Business logic: operations on documents that span PostgreSQL and Elasticsearch."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.schemas import DocumentCreate, SortOrder
from app.search import SearchIndex


async def search_documents(
    session: AsyncSession,
    index: SearchIndex,
    query: str,
    *,
    limit: int,
    order: SortOrder = SortOrder.desc,
) -> tuple[int, list[Document]]:
    """Find documents by text.

    Elasticsearch picks the ``limit`` most relevant documents (the index stores only
    ``id`` and ``text``), PostgreSQL returns them with all fields ordered by creation
    date. Returns the number of matches in the index and the documents.
    """
    hits = await index.search(query, limit=limit)
    if not hits.ids:
        return hits.total, []

    if order is SortOrder.asc:
        ordering = (Document.created_date.asc(), Document.id.asc())
    else:
        ordering = (Document.created_date.desc(), Document.id.desc())

    result = await session.scalars(select(Document).where(Document.id.in_(hits.ids)).order_by(*ordering))
    return hits.total, list(result.all())


async def get_document(session: AsyncSession, document_id: int) -> Document | None:
    return await session.get(Document, document_id)


async def delete_document(session: AsyncSession, index: SearchIndex, document_id: int) -> bool:
    """Delete a document from PostgreSQL and from the index.

    The row is deleted in a transaction that is committed only after the document
    has been removed from Elasticsearch: if the index is unavailable, the transaction
    is rolled back and both stores stay unchanged. Returns False if the document was
    found in neither of them.
    """
    result = await session.execute(
        delete(Document)
        .where(Document.id == document_id)
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    deleted_from_db = result.scalar_one_or_none() is not None
    try:
        deleted_from_index = await index.delete(document_id)
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return deleted_from_db or deleted_from_index


async def add_documents(
    session: AsyncSession, index: SearchIndex, documents: Sequence[DocumentCreate]
) -> list[Document]:
    """Save documents to PostgreSQL and index them; the row is committed after indexing."""
    rows = [Document(**document.model_dump()) for document in documents]
    session.add_all(rows)
    await session.flush()  # assigns ids
    await index.bulk_index(((row.id, row.text) for row in rows), refresh=True)
    await session.commit()
    return rows


async def reindex_all(session: AsyncSession, index: SearchIndex, *, batch_size: int = 500) -> int:
    """Index every document stored in PostgreSQL. Returns the number of indexed documents."""
    result = await session.stream(select(Document.id, Document.text).order_by(Document.id))
    indexed = 0
    async for batch in result.partitions(batch_size):
        indexed += await index.bulk_index((row.id, row.text) for row in batch)
    await index.refresh()
    return indexed


async def count_documents(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Document)) or 0
