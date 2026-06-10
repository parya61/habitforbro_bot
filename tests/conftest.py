"""Общие фикстуры тестов: изолированная БД в памяти и хелперы создания данных."""
from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.models import Base, Habit, HabitLog, User


@pytest_asyncio.fixture
async def session():
    """Свежая in-memory SQLite на каждый тест (StaticPool — один общий коннект)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def make_habit(
    session, *, frequency: str = "daily", freq_value: str | None = None,
    type: str = "binary",
) -> Habit:
    user = User(telegram_id=1, has_access=True)
    session.add(user)
    await session.flush()
    habit = Habit(
        user_id=user.id,
        title="Тест",
        frequency=frequency,
        freq_value=freq_value,
        type=type,
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)
    return habit


async def add_done(session, habit_id: int, days: list[date], done: bool = True) -> None:
    for d in days:
        session.add(HabitLog(habit_id=habit_id, log_date=d, done=done))
    await session.commit()
