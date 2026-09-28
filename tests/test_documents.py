"""Functional tests: getting and deleting documents."""

from datetime import datetime

import pytest
from elastic_transport import ConnectionError as TransportConnectionError

from app.models import Document
from tests.factories import make_document
from tests.helpers import unreachable_database

DOCUMENTS_URL = "/api/v1/documents"


async def test_get_document_returns_all_fields(client, create_documents):
    (document,) = await create_documents(make_document("Текст документа", datetime(2020, 5, 17, 8, 30), ["VK-7"]))

    response = await client.get(f"{DOCUMENTS_URL}/{document.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": document.id,
        "rubrics": ["VK-7"],
        "text": "Текст документа",
        "created_date": "2020-05-17T08:30:00",
    }


async def test_get_missing_document_returns_404(client):
    response = await client.get(f"{DOCUMENTS_URL}/100500")

    assert response.status_code == 404


async def test_delete_removes_document_from_database_and_index(client, create_documents, database, index):
    doomed, survivor = await create_documents(
        make_document("Красный шар улетел в небо", datetime(2020, 1, 1)),
        make_document("Красный закат над морем", datetime(2020, 1, 2)),
    )

    response = await client.delete(f"{DOCUMENTS_URL}/{doomed.id}")

    assert response.status_code == 204
    assert response.content == b""
    async with database.session() as session:
        assert await session.get(Document, doomed.id) is None
        assert await session.get(Document, survivor.id) is not None
    assert not await index.client.exists(index=index.name, id=str(doomed.id))
    assert await index.client.exists(index=index.name, id=str(survivor.id))

    search = (await client.get(f"{DOCUMENTS_URL}/search", params={"query": "красный"})).json()
    assert search["total"] == 1
    assert [item["id"] for item in search["items"]] == [survivor.id]
    assert (await client.get(f"{DOCUMENTS_URL}/{doomed.id}")).status_code == 404
    assert (await client.delete(f"{DOCUMENTS_URL}/{doomed.id}")).status_code == 404


async def test_delete_missing_document_returns_404(client):
    response = await client.delete(f"{DOCUMENTS_URL}/100500")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document 100500 not found"}


@pytest.mark.parametrize("document_id", ["abc", "0", "-5", "2147483648", "9999999999"])
async def test_delete_with_invalid_id_returns_422(client, document_id):
    response = await client.delete(f"{DOCUMENTS_URL}/{document_id}")

    assert response.status_code == 422


async def test_delete_is_rolled_back_when_index_is_unavailable(
    client, create_documents, database, index, monkeypatch
):
    (document,) = await create_documents(make_document("Документ переживёт сбой", datetime(2020, 1, 1)))

    async def broken_delete(document_id: int) -> bool:
        raise TransportConnectionError("Elasticsearch is down")

    monkeypatch.setattr(index, "delete", broken_delete)

    response = await client.delete(f"{DOCUMENTS_URL}/{document.id}")

    assert response.status_code == 503
    async with database.session() as session:
        assert await session.get(Document, document.id) is not None


@pytest.mark.parametrize("document_id", ["abc", "0", "2147483648", "9999999999"])
async def test_get_with_invalid_id_returns_422(client, document_id):
    response = await client.get(f"{DOCUMENTS_URL}/{document_id}")

    assert response.status_code == 422


async def test_get_returns_503_when_database_is_unavailable(app, client, settings, create_documents):
    (document,) = await create_documents(make_document("Текст документа", datetime(2020, 1, 1)))

    async with unreachable_database(app, settings):
        response = await client.get(f"{DOCUMENTS_URL}/{document.id}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}


async def test_delete_does_nothing_when_database_is_unavailable(app, client, settings, create_documents, index):
    (document,) = await create_documents(make_document("Документ переживёт сбой базы", datetime(2020, 1, 1)))

    async with unreachable_database(app, settings):
        response = await client.delete(f"{DOCUMENTS_URL}/{document.id}")

    assert response.status_code == 503
    assert await index.client.exists(index=index.name, id=str(document.id))
    assert (await client.get(f"{DOCUMENTS_URL}/{document.id}")).status_code == 200
