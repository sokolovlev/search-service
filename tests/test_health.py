"""Functional tests: the health check."""

from tests.helpers import unreachable_database


async def test_health_reports_ok_when_storage_is_available(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": True, "elasticsearch": True}


async def test_health_reports_unavailable_database(app, client, settings):
    async with unreachable_database(app, settings):
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "postgres": False, "elasticsearch": True}


async def test_health_reports_unavailable_elasticsearch(client, index, monkeypatch):
    async def broken_ping() -> bool:
        return False

    monkeypatch.setattr(index, "ping", broken_ping)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "postgres": True, "elasticsearch": False}
