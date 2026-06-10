"""Инициализация движка SQLAlchemy и фабрики сессий."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import config
from db.models import Base

# echo=False — не засоряем логи SQL-запросами; включите True для отладки.
engine = create_async_engine(config.db_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record) -> None:
    """Настройки SQLite для надёжности при одновременных запросах.

    WAL — параллельные чтения не блокируют запись; busy_timeout — ждём снятия
    блокировки вместо ошибки «database is locked»; foreign_keys — включаем
    каскадное удаление логов вместе с привычкой.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


async def init_db() -> None:
    """Создаёт таблицы при первом запуске, если их ещё нет."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер для одной сессии БД."""
    async with async_session_factory() as session:
        yield session
