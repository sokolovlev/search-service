"""FastAPI application."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from elastic_transport import ApiError, TransportError
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import InterfaceError as SAInterfaceError

from app.api import documents_router, service_router
from app.config import Settings, get_settings
from app.db import Database
from app.search import SearchIndex

logger = logging.getLogger(__name__)

DESCRIPTION = """Простой поисковик по текстам документов.

* Документы хранятся в PostgreSQL: `id`, `rubrics`, `text`, `created_date`.
* Полнотекстовый индекс — Elasticsearch: `id`, `text` (анализатор `russian`).
* Поиск возвращает 20 самых релевантных документов со всеми полями из базы данных, \
упорядоченных по дате создания.
"""


async def search_backend_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Elasticsearch is down or failed: answer 503 instead of a bare 500."""
    logger.error("Elasticsearch request failed: %r", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Search backend is unavailable"},
    )


# Exceptions that may mean "PostgreSQL is unavailable"; database_error_handler decides.
DATABASE_ERRORS: tuple[type[Exception], ...] = (DBAPIError, asyncpg.PostgresError, asyncpg.InterfaceError, OSError)

# SQLSTATE classes: 08 connection exception, 53 insufficient resources, 57 operator intervention
# (server shutting down, starting up, statement cancelled).
_UNAVAILABLE_SQLSTATE_CLASSES = frozenset({"08", "53", "57"})


def is_database_unavailable(exc: BaseException) -> bool:
    """True if the error means the database cannot be reached, not a bug in a query."""
    # A new connection could not be opened: refused, unknown host, timeout.
    if isinstance(exc, (OSError, asyncpg.InterfaceError)):
        return True
    if isinstance(exc, DBAPIError):
        if exc.connection_invalidated or isinstance(exc, (OperationalError, SAInterfaceError)):
            return True
        exc = exc.orig
    sqlstate = getattr(exc, "sqlstate", None)
    return isinstance(sqlstate, str) and sqlstate[:2] in _UNAVAILABLE_SQLSTATE_CLASSES


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """PostgreSQL is down: answer 503. Any other database error stays a 500."""
    if not is_database_unavailable(exc):
        raise exc
    logger.error("Database request failed: %r", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database is unavailable"},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_url)
        index = SearchIndex(settings.elasticsearch_url, settings.elasticsearch_index)
        try:
            # Idempotent: the table and the index are created only if they are missing.
            await database.create_tables()
            await index.create()
            app.state.database = database
            app.state.index = index
            yield
        finally:
            await index.close()
            await database.close()

    app = FastAPI(
        title="Document Search Service",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_url="/docs.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_exception_handler(ApiError, search_backend_error_handler)
    app.add_exception_handler(TransportError, search_backend_error_handler)
    for error in DATABASE_ERRORS:
        app.add_exception_handler(error, database_error_handler)
    app.include_router(documents_router)
    app.include_router(service_router)
    return app


app = create_app()
