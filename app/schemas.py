"""Pydantic schemas of the API (descriptions end up in docs.json, so they are in Russian)."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SortOrder(str, Enum):
    """Порядок сортировки результатов по дате создания."""

    asc = "asc"
    desc = "desc"


class DocumentCreate(BaseModel):
    """Данные нового документа (загрузка датасета, тесты)."""

    rubrics: list[str] = Field(default_factory=list)
    text: str
    created_date: datetime


class DocumentOut(BaseModel):
    """Документ со всеми полями из базы данных."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Уникальный идентификатор документа", examples=[42])
    rubrics: list[str] = Field(
        description="Рубрики документа", examples=[["VK-1603736028819866", "VK-47360980"]]
    )
    text: str = Field(description="Текст документа", examples=["Сегодня отличная погода для прогулки"])
    created_date: datetime = Field(description="Дата создания документа", examples=["2019-11-25T12:34:42"])


class SearchResponse(BaseModel):
    """Результат поиска."""

    total: int = Field(description="Сколько документов в индексе соответствует запросу", examples=[137])
    items: list[DocumentOut] = Field(
        description="Не более 20 самых релевантных документов, упорядоченных по дате создания"
    )


class ErrorResponse(BaseModel):
    """Описание ошибки."""

    detail: str = Field(description="Текст ошибки", examples=["Document 42 not found"])


class HealthResponse(BaseModel):
    """Состояние сервиса и его зависимостей."""

    status: Literal["ok", "unavailable"] = Field(description="Общее состояние сервиса")
    postgres: bool = Field(description="PostgreSQL доступен")
    elasticsearch: bool = Field(description="Elasticsearch доступен")
