"""Async SQLAlchemy engine and sessions."""

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base


class Database:
    """Owns the engine (connection pool) and the session factory."""

    def __init__(self, url: URL | str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
            connect_args={"timeout": 10},
        )
        self._session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def create_tables(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def close(self) -> None:
        await self.engine.dispose()
