"""Dataset import: CSV -> PostgreSQL -> Elasticsearch.

    python -m app.loader [PATH] [--download] [--recreate]
    python -m app.loader --reindex

Rows are inserted into PostgreSQL first; the index is then built from the database,
so ids in Elasticsearch always match ids in PostgreSQL.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import insert

from app import services
from app.config import Settings, get_settings
from app.dataset import DATASET_PUBLIC_URL, DatasetRow, ReadStats, download_dataset, read_csv
from app.db import Database
from app.models import Document
from app.search import SearchIndex

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path("data/posts.csv")
BATCH_SIZE = 500

T = TypeVar("T")


class DatasetAlreadyLoadedError(RuntimeError):
    """The table already has documents and ``recreate`` was not requested."""


@dataclass(slots=True)
class LoadReport:
    inserted: int
    indexed: int
    skipped: int


async def load_dataset(path: Path, settings: Settings, *, recreate: bool = False) -> LoadReport:
    """Import documents from a CSV file into PostgreSQL and index them in Elasticsearch."""
    database = Database(settings.database_url)
    index = SearchIndex(settings.elasticsearch_url, settings.elasticsearch_index)
    try:
        if recreate:
            await database.drop_tables()
        await database.create_tables()

        async with database.session() as session:
            existing = await services.count_documents(session)
            if existing:
                raise DatasetAlreadyLoadedError(
                    f"the documents table already contains {existing} rows; "
                    "run with --recreate to load the dataset again "
                    "or with --reindex to rebuild only the Elasticsearch index"
                )
            # PostgreSQL is the source of truth: an empty table means an empty index.
            await index.drop()
            await index.create()

            stats = ReadStats()
            inserted = 0
            for batch in _chunked(read_csv(path, stats), BATCH_SIZE):
                await session.execute(insert(Document), [_row_values(row) for row in batch])
                inserted += len(batch)
            await session.commit()

            try:
                indexed = await services.reindex_all(session, index)
            except Exception:
                logger.error(
                    "Documents are saved to PostgreSQL, but indexing failed: "
                    "run with --reindex to rebuild the index"
                )
                raise
        return LoadReport(inserted=inserted, indexed=indexed, skipped=stats.skipped)
    finally:
        await index.close()
        await database.close()


async def rebuild_index(settings: Settings) -> int:
    """Recreate the Elasticsearch index from the documents stored in PostgreSQL."""
    database = Database(settings.database_url)
    index = SearchIndex(settings.elasticsearch_url, settings.elasticsearch_index)
    try:
        await index.drop()
        await index.create()
        async with database.session() as session:
            return await services.reindex_all(session, index)
    finally:
        await index.close()
        await database.close()


def _row_values(row: DatasetRow) -> dict[str, Any]:
    return {"text": row.text, "created_date": row.created_date, "rubrics": row.rubrics}


def _chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.loader",
        description="Load the documents dataset (CSV) into PostgreSQL and Elasticsearch.",
    )
    parser.add_argument(
        "path", nargs="?", type=Path, default=DEFAULT_DATASET_PATH, help="CSV file (default: %(default)s)"
    )
    parser.add_argument(
        "--download", action="store_true", help="download the dataset from Yandex Disk if the file is missing"
    )
    parser.add_argument("--url", default=DATASET_PUBLIC_URL, help="public Yandex Disk link (default: %(default)s)")
    parser.add_argument("--recreate", action="store_true", help="drop all documents and load the dataset again")
    parser.add_argument("--reindex", action="store_true", help="only rebuild the index from PostgreSQL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    settings = get_settings()

    if args.reindex:
        indexed = asyncio.run(rebuild_index(settings))
        logger.info("Index %r rebuilt: %d documents", settings.elasticsearch_index, indexed)
        return 0

    if not args.path.exists():
        if not args.download:
            logger.error(
                "Dataset %s not found: download it from %s or run with --download", args.path, args.url
            )
            return 1
        logger.info("Downloading the dataset from %s to %s", args.url, args.path)
        try:
            asyncio.run(download_dataset(args.path, args.url))
        except Exception as exc:  # network problems, unexpected API response, ...
            logger.error(
                "Could not download the dataset (%s). Download it manually from %s and save it as %s",
                exc,
                args.url,
                args.path,
            )
            return 1

    try:
        report = asyncio.run(load_dataset(args.path, settings, recreate=args.recreate))
    except DatasetAlreadyLoadedError as exc:
        logger.error("%s", exc)
        return 1
    logger.info(
        "Done: %d documents saved to PostgreSQL, %d indexed in Elasticsearch, %d malformed rows skipped",
        report.inserted,
        report.indexed,
        report.skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
