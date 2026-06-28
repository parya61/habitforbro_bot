"""Слой доступа к данным: создание/чтение/обновление сущностей.

Здесь нет бизнес-логики серий и статистики (она в services/),
только сами запросы к базе.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import (
    Achievement,
    DiaryEntry,
    Habit,
    HabitLog,
    Prize,
    TeaProfile,
    TeaSession,
    User,
)


# ---------- Пользователи ----------

async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> User | None:
    res = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return res.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    name: str | None,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=username,
        name=name,
        timezone=config.default_timezone,
        has_access=False,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def grant_access(session: AsyncSession, user: User) -> None:
    user.has_access = True
    await session.commit()


async def list_users(session: AsyncSession) -> list[User]:
    res = await session.execute(
        select(User).where(User.has_access.is_(True)).order_by(User.registered_at)
    )
    return list(res.scalars().all())


async def update_user_settings(session: AsyncSession, user: User, **fields) -> None:
    for key, value in fields.items():
        setattr(user, key, value)
    await session.commit()


# ---------- Привычки ----------

async def create_habit(session: AsyncSession, **fields) -> Habit:
    habit = Habit(**fields)
    session.add(habit)
    await session.commit()
    await session.refresh(habit)
    return habit


async def get_habit(session: AsyncSession, habit_id: int) -> Habit | None:
    res = await session.execute(select(Habit).where(Habit.id == habit_id))
    return res.scalar_one_or_none()


async def list_habits(
    session: AsyncSession, user_id: int, *, include_archived: bool = False
) -> list[Habit]:
    stmt = select(Habit).where(Habit.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Habit.status == "active")
    stmt = stmt.order_by(Habit.created_at)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_public_habits(session: AsyncSession, user_id: int) -> list[Habit]:
    """Только публичные активные привычки — для показа другим участникам."""
    res = await session.execute(
        select(Habit)
        .where(
            Habit.user_id == user_id,
            Habit.status == "active",
            Habit.privacy == "public",
        )
        .order_by(Habit.created_at)
    )
    return list(res.scalars().all())


async def update_habit(session: AsyncSession, habit: Habit, **fields) -> None:
    for key, value in fields.items():
        setattr(habit, key, value)
    await session.commit()


async def list_archived_habits(session: AsyncSession, user_id: int) -> list[Habit]:
    """Архивированные привычки пользователя (для просмотра и восстановления)."""
    res = await session.execute(
        select(Habit)
        .where(Habit.user_id == user_id, Habit.status == "archived")
        .order_by(Habit.created_at)
    )
    return list(res.scalars().all())


async def archive_habit(session: AsyncSession, habit: Habit) -> None:
    habit.status = "archived"
    await session.commit()


async def restore_habit(session: AsyncSession, habit: Habit) -> None:
    habit.status = "active"
    await session.commit()


# ---------- Отметки привычек ----------

async def get_log(
    session: AsyncSession, habit_id: int, log_date: date
) -> HabitLog | None:
    res = await session.execute(
        select(HabitLog).where(
            HabitLog.habit_id == habit_id, HabitLog.log_date == log_date
        )
    )
    return res.scalar_one_or_none()


async def upsert_log(
    session: AsyncSession,
    habit_id: int,
    log_date: date,
    *,
    done: bool,
    amount: int | None = None,
    note: str | None = None,
) -> HabitLog:
    log = await get_log(session, habit_id, log_date)
    if log is None:
        log = HabitLog(habit_id=habit_id, log_date=log_date)
        session.add(log)
    log.done = done
    if amount is not None:
        log.amount = amount
    if note is not None:
        log.note = note
    await session.commit()
    await session.refresh(log)
    return log


async def get_logs_range(
    session: AsyncSession, habit_id: int, start: date, end: date
) -> list[HabitLog]:
    res = await session.execute(
        select(HabitLog)
        .where(
            HabitLog.habit_id == habit_id,
            HabitLog.log_date >= start,
            HabitLog.log_date <= end,
        )
        .order_by(HabitLog.log_date)
    )
    return list(res.scalars().all())


# ---------- Дневник ----------

async def add_diary_entry(
    session: AsyncSession,
    user_id: int,
    entry_date: date,
    text: str,
    mood: str | None,
    private: bool,
) -> DiaryEntry:
    entry = DiaryEntry(
        user_id=user_id,
        entry_date=entry_date,
        text=text,
        mood=mood,
        private=private,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def list_diary_entries(
    session: AsyncSession, user_id: int, limit: int = 30
) -> list[DiaryEntry]:
    res = await session.execute(
        select(DiaryEntry)
        .where(DiaryEntry.user_id == user_id)
        .order_by(DiaryEntry.entry_date.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


# ---------- Достижения ----------

async def has_achievement(
    session: AsyncSession, user_id: int, code: str, habit_id: int | None
) -> bool:
    res = await session.execute(
        select(Achievement).where(
            Achievement.user_id == user_id,
            Achievement.code == code,
            Achievement.habit_id == habit_id,
        )
    )
    return res.scalar_one_or_none() is not None


async def add_achievement(
    session: AsyncSession, user_id: int, code: str, habit_id: int | None = None
) -> Achievement | None:
    """Добавляет достижение, если его ещё нет. Возвращает новое или None."""
    if await has_achievement(session, user_id, code, habit_id):
        return None
    ach = Achievement(user_id=user_id, code=code, habit_id=habit_id)
    session.add(ach)
    await session.commit()
    await session.refresh(ach)
    return ach


async def list_achievements(session: AsyncSession, user_id: int) -> list[Achievement]:
    res = await session.execute(
        select(Achievement)
        .where(Achievement.user_id == user_id)
        .order_by(Achievement.earned_at.desc())
    )
    return list(res.scalars().all())


# ---------- Призы ----------

async def get_prize(session: AsyncSession, month: str) -> Prize | None:
    res = await session.execute(select(Prize).where(Prize.month == month))
    return res.scalar_one_or_none()


async def set_prize(
    session: AsyncSession, month: str, description: str, prize_code: str | None
) -> Prize:
    prize = await get_prize(session, month)
    if prize is None:
        prize = Prize(month=month, description=description, prize_code=prize_code)
        session.add(prize)
    else:
        prize.description = description
        prize.prize_code = prize_code
    await session.commit()
    await session.refresh(prize)
    return prize


async def set_prize_winner(
    session: AsyncSession, prize: Prize, user_id: int
) -> None:
    from datetime import datetime
    prize.winner_user_id = user_id
    prize.announced_at = datetime.utcnow()
    await session.commit()


async def list_prizes(session: AsyncSession, limit: int = 12) -> list[Prize]:
    res = await session.execute(
        select(Prize).order_by(Prize.month.desc()).limit(limit)
    )
    return list(res.scalars().all())


# ---------- Чайный профиль ----------

async def get_tea_profile(session: AsyncSession, user_id: int) -> TeaProfile | None:
    res = await session.execute(
        select(TeaProfile).where(TeaProfile.user_id == user_id)
    )
    return res.scalar_one_or_none()


async def upsert_tea_profile(session: AsyncSession, user_id: int, **fields) -> TeaProfile:
    profile = await get_tea_profile(session, user_id)
    if profile is None:
        profile = TeaProfile(user_id=user_id, **fields)
        session.add(profile)
    else:
        for k, v in fields.items():
            setattr(profile, k, v)
    await session.commit()
    await session.refresh(profile)
    return profile


# ---------- Чайные записи ----------

async def add_tea_session(session: AsyncSession, **fields) -> TeaSession:
    ts = TeaSession(**fields)
    session.add(ts)
    await session.commit()
    await session.refresh(ts)
    return ts


async def list_tea_sessions(
    session: AsyncSession, user_id: int, limit: int = 20
) -> list[TeaSession]:
    res = await session.execute(
        select(TeaSession)
        .where(TeaSession.user_id == user_id)
        .order_by(TeaSession.session_date.desc(), TeaSession.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def count_tea_sessions(session: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func
    res = await session.scalar(
        select(func.count()).select_from(TeaSession).where(TeaSession.user_id == user_id)
    )
    return res or 0


async def tea_type_stats(session: AsyncSession, user_id: int) -> list[tuple[str, int]]:
    from sqlalchemy import func
    res = await session.execute(
        select(TeaSession.tea_type, func.count())
        .where(TeaSession.user_id == user_id)
        .group_by(TeaSession.tea_type)
        .order_by(func.count().desc())
    )
    return list(res.all())


async def tea_name_stats(session: AsyncSession, user_id: int, limit: int = 5) -> list[tuple[str, int]]:
    from sqlalchemy import func
    res = await session.execute(
        select(TeaSession.tea_name, func.count())
        .where(TeaSession.user_id == user_id)
        .group_by(TeaSession.tea_name)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return list(res.all())


async def tea_session_dates(session: AsyncSession, user_id: int) -> list[date]:
    from sqlalchemy import func
    res = await session.execute(
        select(TeaSession.session_date)
        .where(TeaSession.user_id == user_id)
        .group_by(TeaSession.session_date)
        .order_by(TeaSession.session_date.desc())
    )
    return [row[0] for row in res.all()]


async def avg_tea_rating(session: AsyncSession, user_id: int) -> float | None:
    from sqlalchemy import func
    res = await session.scalar(
        select(func.avg(TeaSession.rating))
        .where(TeaSession.user_id == user_id, TeaSession.rating.isnot(None))
    )
    return round(float(res), 1) if res else None
