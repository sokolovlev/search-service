"""HTTP API."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from fastapi.exceptions import RequestValidationError

from app import services
from app.dependencies import DatabaseDep, IndexDep, SessionDep, SettingsDep
from app.schemas import DocumentOut, ErrorResponse, HealthResponse, SearchResponse, SortOrder

documents_router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
service_router = APIRouter(tags=["service"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Документ не найден"}}
STORAGE_UNAVAILABLE = {503: {"model": ErrorResponse, "description": "PostgreSQL или Elasticsearch недоступен"}}
DATABASE_UNAVAILABLE = {503: {"model": ErrorResponse, "description": "PostgreSQL недоступен"}}

# The column is int4 (PostgreSQL INTEGER): larger ids would fail in asyncpg with a 500.
MAX_DOCUMENT_ID = 2_147_483_647

DocumentId = Annotated[int, Path(ge=1, le=MAX_DOCUMENT_ID, description="Идентификатор документа", examples=[42])]


# Must be declared before "/{document_id}", otherwise "search" would be taken for an id.
@documents_router.get(
    "/search",
    response_model=SearchResponse,
    summary="Поиск документов",
    description=(
        "Ищет произвольный текстовый запрос по полю `text` в индексе Elasticsearch "
        "(с учётом русской морфологии), берёт 20 самых релевантных документов и возвращает их "
        "со всеми полями из базы данных, упорядоченными по дате создания."
    ),
    responses=STORAGE_UNAVAILABLE,
)
async def search_documents(
    session: SessionDep,
    index: IndexDep,
    settings: SettingsDep,
    query: Annotated[
        str,
        Query(
            min_length=1,
            max_length=1000,
            description="Произвольный текстовый запрос",
            examples=["отличная погода"],
        ),
    ],
    order: Annotated[
        SortOrder,
        Query(description="Порядок сортировки по дате создания: `desc` — сначала новые, `asc` — сначала старые"),
    ] = SortOrder.desc,
) -> SearchResponse:
    text = query.strip()
    if not text:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("query", "query"), "msg": "Query must not be blank", "input": query}]
        )
    total, documents = await services.search_documents(
        session, index, text, limit=settings.search_limit, order=order
    )
    return SearchResponse(total=total, items=[DocumentOut.model_validate(document) for document in documents])


@documents_router.get(
    "/{document_id}",
    response_model=DocumentOut,
    summary="Получить документ",
    description="Возвращает документ по `id` со всеми полями из базы данных.",
    responses={**NOT_FOUND, **DATABASE_UNAVAILABLE},
)
async def get_document(document_id: DocumentId, session: SessionDep) -> DocumentOut:
    document = await services.get_document(session, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return DocumentOut.model_validate(document)


@documents_router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Удалить документ",
    description=(
        "Удаляет документ по `id` из базы данных и из индекса Elasticsearch. "
        "Если PostgreSQL или Elasticsearch недоступен, удаление отменяется целиком."
    ),
    responses={**NOT_FOUND, **STORAGE_UNAVAILABLE},
)
async def delete_document(document_id: DocumentId, session: SessionDep, index: IndexDep) -> Response:
    if not await services.delete_document(session, index, document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@service_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Состояние сервиса",
    description="Проверяет доступность PostgreSQL и Elasticsearch.",
    responses={503: {"model": HealthResponse, "description": "PostgreSQL или Elasticsearch недоступен"}},
)
async def health(database: DatabaseDep, index: IndexDep, response: Response) -> HealthResponse:
    postgres_ok, elasticsearch_ok = await asyncio.gather(database.ping(), index.ping())
    healthy = postgres_ok and elasticsearch_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "unavailable",
        postgres=postgres_ok,
        elasticsearch=elasticsearch_ok,
    )
