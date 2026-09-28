"""The dataset: CSV parsing and downloading from a public Yandex Disk link."""

import ast
import csv
import json
import logging
import shutil
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DATASET_PUBLIC_URL = "https://disk.yandex.ru/d/UYooXd9q2yqTMQ"
YANDEX_DOWNLOAD_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"

REQUIRED_COLUMNS = frozenset({"text", "created_date", "rubrics"})
_FALLBACK_DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y")


@dataclass(slots=True)
class DatasetRow:
    text: str
    created_date: datetime
    rubrics: list[str]


@dataclass(slots=True)
class ReadStats:
    read: int = 0
    skipped: int = 0


def parse_rubrics(raw: str | None) -> list[str]:
    """Parse the ``rubrics`` column.

    The dataset stores rubrics as a Python list literal (``['VK-1', 'VK-2']``);
    JSON arrays, PostgreSQL array literals (``{a,b}``) and comma-separated
    strings are accepted as well.
    """
    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith("["):
        for parse in (ast.literal_eval, json.loads):
            try:
                parsed = parse(value)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                continue
            if isinstance(parsed, (list, tuple)):
                # None / null elements are gaps in the list, not a rubric named "None".
                items = (str(item).strip() for item in parsed if item is not None)
                return [item for item in items if item]
        raise ValueError(f"cannot parse rubrics: {raw!r}")
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    items = (item.strip().strip("\"'").strip() for item in value.split(","))
    return [item for item in items if item]


def parse_text(raw: str | None) -> str:
    """Return the document text as is; a document without text cannot be found, so it is rejected."""
    if not raw or not raw.strip():
        raise ValueError("empty text")
    return raw


def parse_date(raw: str | None) -> datetime:
    """Parse the creation date; timezone-aware values are converted to naive UTC."""
    parsed = _parse_datetime((raw or "").strip())
    if parsed is None:
        raise ValueError(f"unsupported date format: {raw!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for date_format in _FALLBACK_DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def read_csv(path: Path, stats: ReadStats | None = None) -> Iterator[DatasetRow]:
    """Yield rows of the dataset. Malformed rows are logged and skipped (counted in ``stats``)."""
    stats = stats if stats is not None else ReadStats()
    csv.field_size_limit(2**31 - 1)  # long texts
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = {_normalize(name) for name in reader.fieldnames or ()}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"{path}: missing CSV columns: {', '.join(sorted(missing))}")
        for raw_row in reader:
            row = {_normalize(key): value for key, value in raw_row.items() if isinstance(key, str)}
            try:
                parsed = DatasetRow(
                    text=parse_text(row["text"]),
                    created_date=parse_date(row["created_date"]),
                    rubrics=parse_rubrics(row["rubrics"]),
                )
            except ValueError as exc:
                stats.skipped += 1
                logger.warning("%s:%d: row skipped: %s", path, reader.line_num, exc)
                continue
            stats.read += 1
            yield parsed


def _normalize(column: str) -> str:
    return column.strip().lstrip("\ufeff").lower()


async def download_dataset(destination: Path, public_url: str = DATASET_PUBLIC_URL) -> None:
    """Download the dataset via the public Yandex Disk REST API (no token required)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(YANDEX_DOWNLOAD_API, params={"public_key": public_url})
            response.raise_for_status()
            async with client.stream("GET", response.json()["href"]) as stream:
                stream.raise_for_status()
                with partial.open("wb") as file:
                    async for chunk in stream.aiter_bytes():
                        file.write(chunk)
        if zipfile.is_zipfile(partial):
            # A public folder is downloaded as a zip archive: take the first CSV from it.
            _extract_first_csv(partial, destination)
        else:
            partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _extract_first_csv(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as zip_file:
        names = sorted(name for name in zip_file.namelist() if name.lower().endswith(".csv"))
        if not names:
            raise ValueError("the downloaded archive contains no CSV files")
        with zip_file.open(names[0]) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
