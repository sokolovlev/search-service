"""Functional tests: dataset import (CSV -> PostgreSQL -> Elasticsearch)."""

import pytest

from app import services
from app.loader import DatasetAlreadyLoadedError, load_dataset

CSV_CONTENT = (
    "text,created_date,rubrics\n"
    "\"Первая заметка про котов\",2019-11-25 12:34:42,\"['VK-1603736028819866', 'VK-47360980']\"\n"
    "\"Вторая заметка\nпро котов в две строки\",2020-01-05 08:00:00,['VK-1']\n"
    "Третья заметка про собак,2018-03-10 23:59:59,[]\n"
    "Строка без даты,,[]\n"
)


@pytest.fixture
def dataset_path(tmp_path):
    path = tmp_path / "posts.csv"
    path.write_text(CSV_CONTENT, encoding="utf-8")
    return path


async def test_load_dataset_fills_database_and_index(client, settings, dataset_path):
    report = await load_dataset(dataset_path, settings)

    assert (report.inserted, report.indexed, report.skipped) == (3, 3, 1)
    response = await client.get("/api/v1/documents/search", params={"query": "коты"})
    items = response.json()["items"]
    assert [item["text"] for item in items] == ["Вторая заметка\nпро котов в две строки", "Первая заметка про котов"]
    assert items[1]["rubrics"] == ["VK-1603736028819866", "VK-47360980"]
    assert items[1]["created_date"] == "2019-11-25T12:34:42"


async def test_load_dataset_does_not_duplicate_documents(settings, database, index, dataset_path):
    await load_dataset(dataset_path, settings)

    with pytest.raises(DatasetAlreadyLoadedError):
        await load_dataset(dataset_path, settings)

    report = await load_dataset(dataset_path, settings, recreate=True)

    assert report.inserted == 3
    async with database.session() as session:
        assert await services.count_documents(session) == 3
    assert (await index.client.count(index=index.name))["count"] == 3
