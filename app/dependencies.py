"""FastAPI dependencies: resources created in the application lifespan."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Database
from app.search import SearchIndex


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_index(request: Request) -> SearchIndex:
    return request.app.state.index


async def get_session(database: Annotated[Database, Depends(get_database)]) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
IndexDep = Annotated[SearchIndex, Depends(get_index)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
