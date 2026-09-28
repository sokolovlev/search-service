"""Helpers for simulating unavailable storage in functional tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import Database


@asynccontextmanager
async def unreachable_database(app: FastAPI, settings: Settings) -> AsyncIterator[Database]:
    """Point the application at a PostgreSQL port where nothing listens (as if the database is down)."""
    unreachable = Database(settings.model_copy(update={"postgres_port": 1}).database_url)
    original = app.state.database
    app.state.database = unreachable
    try:
        yield unreachable
    finally:
        app.state.database = original
        await unreachable.close()
