"""Fixtures for the functional tests.

Tests talk to real PostgreSQL and Elasticsearch (the ``tests`` service in
docker-compose.yml) but always use a separate database and index, so the main
data is never touched. Both are emptied before every test.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable

import asyncpg
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import services
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Document
from app.schemas import DocumentCreate
from app.search import SearchIndex

_database_checked = False
_storage_created = False


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        postgres_db=os.getenv("TEST_POSTGRES_DB", "search_test"),
        elasticsearch_index=os.getenv("TEST_ELASTICSEARCH_INDEX", "documents_test"),
        search_limit=20,
    )


async def _create_database_if_missing(settings: Settings) -> None:
    global _database_checked
    if _database_checked:
        return
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", settings.postgres_db)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await connection.close()
    _database_checked = True


async def _reset_storage(database: Database, index: SearchIndex) -> None:
    global _storage_created
    if not _storage_created:
        # The first test of the session starts from a fresh schema and mapping.
        await database.drop_tables()
        await database.create_tables()
        await index.drop()
        await index.create()
        _storage_created = True
        return
    async with database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE documents RESTART IDENTITY"))
    await index.client.delete_by_query(
        index=index.name, query={"match_all": {}}, refresh=True, conflicts="proceed"
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    await _create_database_if_missing(settings)
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        await _reset_storage(application.state.database, application.state.index)
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def database(app: FastAPI) -> Database:
    return app.state.database


@pytest.fixture
def index(app: FastAPI) -> SearchIndex:
    return app.state.index


@pytest.fixture
def create_documents(database: Database, index: SearchIndex) -> Callable[..., Awaitable[list[Document]]]:
    """Save documents to the test database and index them (the index is refreshed)."""

    async def _create(*documents: DocumentCreate) -> list[Document]:
        async with database.session() as session:
            return await services.add_documents(session, index, documents)

    return _create
