"""Elasticsearch index with documents: ``id`` + ``text`` (Russian analyzer).

The ``_id`` of an indexed document equals its ``id`` in PostgreSQL.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from elasticsearch import AsyncElasticsearch, BadRequestError, NotFoundError
from elasticsearch.helpers import async_bulk

logger = logging.getLogger(__name__)

INDEX_SETTINGS: dict[str, Any] = {"number_of_shards": 1, "number_of_replicas": 0}
INDEX_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "id": {"type": "long"},
        # Built-in analyzer: lowercase + Russian stop words + Snowball stemmer,
        # so "машины" finds "машину".
        "text": {"type": "text", "analyzer": "russian"},
    },
}


@dataclass(frozen=True, slots=True)
class SearchHits:
    total: int  # number of matching documents in the index
    ids: list[int]  # ids of the best matches, most relevant first


class SearchIndex:
    def __init__(self, url: str, name: str) -> None:
        self.name = name
        # One retry at most: a request to a dead cluster fails in seconds instead of hanging
        # (DELETE holds a row lock in PostgreSQL while it waits for Elasticsearch).
        self.client = AsyncElasticsearch(url, request_timeout=10, max_retries=1, retry_on_timeout=True)

    async def create(self) -> bool:
        """Create the index if it does not exist yet. Returns True if it was created."""
        if await self.client.indices.exists(index=self.name):
            return False
        try:
            await self.client.indices.create(index=self.name, settings=INDEX_SETTINGS, mappings=INDEX_MAPPINGS)
        except BadRequestError as exc:
            if _error_type(exc) == "resource_already_exists_exception":  # created concurrently
                return False
            raise
        logger.info("Created Elasticsearch index %r", self.name)
        return True

    async def drop(self) -> None:
        await self.client.options(ignore_status=404).indices.delete(index=self.name)

    async def search(self, query: str, *, limit: int) -> SearchHits:
        """Full-text search by ``text``; returns ids of the ``limit`` most relevant documents."""
        response = await self.client.search(
            index=self.name,
            query={"match": {"text": query}},
            size=limit,
            source=False,
            track_total_hits=True,
        )
        hits = response["hits"]
        return SearchHits(
            total=hits["total"]["value"],
            ids=[int(hit["_id"]) for hit in hits["hits"]],
        )

    async def delete(self, document_id: int) -> bool:
        """Delete a document from the index. Returns False if it was not there."""
        try:
            await self.client.delete(index=self.name, id=str(document_id), refresh="wait_for")
        except NotFoundError:
            return False
        return True

    async def bulk_index(self, documents: Iterable[tuple[int, str]], *, refresh: bool = False) -> int:
        """Index ``(id, text)`` pairs with the bulk API. Returns the number of indexed documents."""
        actions = (
            {"_index": self.name, "_id": str(document_id), "_source": {"id": document_id, "text": text}}
            for document_id, text in documents
        )
        indexed, _ = await async_bulk(self.client, actions, chunk_size=500)
        if refresh:
            await self.refresh()
        return indexed

    async def refresh(self) -> None:
        await self.client.indices.refresh(index=self.name)

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.close()


def _error_type(exc: BadRequestError) -> str | None:
    body = exc.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("type")
    return None
