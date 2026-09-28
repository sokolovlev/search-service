"""Functional tests: full-text search."""

from datetime import datetime, timedelta

import pytest
from elastic_transport import ConnectionError as TransportConnectionError

from tests.factories import make_document
from tests.helpers import unreachable_database

SEARCH_URL = "/api/v1/documents/search"


async def test_search_returns_documents_with_all_db_fields(client, create_documents):
    cat, _ = await create_documents(
        make_document("Кошка спит на подоконнике", datetime(2019, 11, 25, 12, 34, 42), ["VK-1", "VK-2"]),
        make_document("Собака гуляет во дворе", datetime(2020, 1, 1)),
    )

    response = await client.get(SEARCH_URL, params={"query": "кошка"})

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "items": [
            {
                "id": cat.id,
                "rubrics": ["VK-1", "VK-2"],
                "text": "Кошка спит на подоконнике",
                "created_date": "2019-11-25T12:34:42",
            }
        ],
    }


async def test_search_orders_results_by_created_date(client, create_documents):
    dates = [datetime(2021, 5, 3), datetime(2019, 1, 1), datetime(2022, 12, 31), datetime(2020, 7, 15)]
    await create_documents(*(make_document(f"Прогноз погоды номер {i}", date) for i, date in enumerate(dates)))

    newest_first = await client.get(SEARCH_URL, params={"query": "прогноз"})
    oldest_first = await client.get(SEARCH_URL, params={"query": "прогноз", "order": "asc"})

    assert [item["created_date"] for item in newest_first.json()["items"]] == [
        date.isoformat() for date in sorted(dates, reverse=True)
    ]
    assert [item["created_date"] for item in oldest_first.json()["items"]] == [
        date.isoformat() for date in sorted(dates)
    ]


async def test_search_returns_20_most_relevant_documents_sorted_by_date(client, create_documents):
    start = datetime(2020, 1, 1)
    # Both query words, but older documents.
    relevant = [make_document(f"Синий трактор номер {i}", start + timedelta(days=i)) for i in range(20)]
    # Only one of the words and newer documents: they must not push the relevant ones out of the top 20.
    partial = [make_document(f"Старый трактор номер {i}", start + timedelta(days=100 + i)) for i in range(10)]
    created = await create_documents(*relevant, *partial)

    response = await client.get(SEARCH_URL, params={"query": "синий трактор"})

    body = response.json()
    assert body["total"] == 30
    assert len(body["items"]) == 20
    assert {item["id"] for item in body["items"]} == {document.id for document in created[:20]}
    dates = [item["created_date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True)


async def test_search_understands_russian_word_forms(client, create_documents):
    (document,) = await create_documents(make_document("Вчера мы купили новую машину", datetime(2020, 1, 1)))

    response = await client.get(SEARCH_URL, params={"query": "машины"})

    assert [item["id"] for item in response.json()["items"]] == [document.id]


async def test_search_without_matches_returns_empty_result(client, create_documents):
    await create_documents(make_document("Кошка спит на подоконнике", datetime(2020, 1, 1)))

    response = await client.get(SEARCH_URL, params={"query": "экскаватор"})

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


@pytest.mark.parametrize(
    "params",
    [{}, {"query": ""}, {"query": "   "}, {"query": "кошка", "order": "random"}],
    ids=["missing-query", "empty-query", "blank-query", "unknown-order"],
)
async def test_search_validates_parameters(client, params):
    response = await client.get(SEARCH_URL, params=params)

    assert response.status_code == 422


async def test_search_returns_503_when_elasticsearch_is_unavailable(client, index, monkeypatch):
    async def broken_search(query: str, *, limit: int):
        raise TransportConnectionError("Elasticsearch is down")

    monkeypatch.setattr(index, "search", broken_search)

    response = await client.get(SEARCH_URL, params={"query": "кошка"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Search backend is unavailable"}


async def test_search_returns_503_when_database_is_unavailable(app, client, settings, create_documents):
    # A match in the index is needed: without hits the database is not queried at all.
    await create_documents(make_document("Кошка спит на подоконнике", datetime(2020, 1, 1)))

    async with unreachable_database(app, settings):
        response = await client.get(SEARCH_URL, params={"query": "кошка"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
