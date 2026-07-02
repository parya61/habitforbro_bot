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
    TeaCollection,
    TeaProfile,
    TeaSession,
    TeawareItem,
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




async def set_prize_winners(
    session: AsyncSession,
    prize: Prize,
    winner_1_id: int | None,
    winner_2_id: int | None = None,
    winner_3_id: int | None = None,
) -> None:
    from datetime import datetime

    prize.winner_user_id = winner_1_id
    prize.winner_2_user_id = winner_2_id
    prize.winner_3_user_id = winner_3_id
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
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    tea_type: str | None = None,
    min_rating: int | None = None,
) -> list[TeaSession]:
    q = select(TeaSession).where(TeaSession.user_id == user_id)
    if tea_type:
        q = q.where(TeaSession.tea_type == tea_type)
    if min_rating:
        q = q.where(TeaSession.rating >= min_rating)
    q = q.order_by(TeaSession.session_date.desc(), TeaSession.created_at.desc())
    res = await session.execute(q.offset(offset).limit(limit))
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


async def list_public_tea_sessions(
    session: AsyncSession, limit: int = 15, offset: int = 0
) -> list[TeaSession]:
    from sqlalchemy.orm import joinedload
    res = await session.execute(
        select(TeaSession)
        .options(joinedload(TeaSession.user))
        .where(TeaSession.private.is_(False))
        .order_by(TeaSession.session_date.desc(), TeaSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(res.scalars().all())


async def list_user_public_tea_sessions(
    session: AsyncSession, user_id: int, limit: int = 10
) -> list[TeaSession]:
    res = await session.execute(
        select(TeaSession)
        .where(TeaSession.user_id == user_id, TeaSession.private.is_(False))
        .order_by(TeaSession.session_date.desc(), TeaSession.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def get_tea_session(session: AsyncSession, ts_id: int) -> TeaSession | None:
    from sqlalchemy.orm import joinedload
    res = await session.execute(
        select(TeaSession)
        .options(joinedload(TeaSession.user))
        .where(TeaSession.id == ts_id)
    )
    return res.scalar_one_or_none()


async def update_tea_session(session: AsyncSession, ts_id: int, **fields) -> TeaSession | None:
    ts = await get_tea_session(session, ts_id)
    if ts is None:
        return None
    for k, v in fields.items():
        setattr(ts, k, v)
    await session.commit()
    await session.refresh(ts)
    return ts


async def delete_tea_session(session: AsyncSession, ts_id: int) -> bool:
    ts = await get_tea_session(session, ts_id)
    if ts is None:
        return False
    await session.delete(ts)
    await session.commit()
    return True


# ---------- Чайная коллекция ----------

async def add_tea_collection(session: AsyncSession, **fields) -> TeaCollection:
    item = TeaCollection(**fields)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def get_tea_collection_item(session: AsyncSession, item_id: int) -> TeaCollection | None:
    res = await session.execute(
        select(TeaCollection).where(TeaCollection.id == item_id)
    )
    return res.scalar_one_or_none()


async def list_tea_collection(
    session: AsyncSession, user_id: int, *, include_finished: bool = False
) -> list[TeaCollection]:
    stmt = select(TeaCollection).where(TeaCollection.user_id == user_id)
    if not include_finished:
        stmt = stmt.where(TeaCollection.status == "active")
    stmt = stmt.order_by(TeaCollection.created_at.desc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def update_tea_collection_item(session: AsyncSession, item_id: int, **fields) -> TeaCollection | None:
    item = await get_tea_collection_item(session, item_id)
    if item is None:
        return None
    for k, v in fields.items():
        setattr(item, k, v)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_tea_collection_item(session: AsyncSession, item_id: int) -> bool:
    item = await get_tea_collection_item(session, item_id)
    if item is None:
        return False
    await session.delete(item)
    await session.commit()
    return True


async def subtract_tea_grams(session: AsyncSession, item_id: int, grams: int) -> TeaCollection | None:
    item = await get_tea_collection_item(session, item_id)
    if item is None:
        return None
    if item.remaining_grams is not None:
        item.remaining_grams = max(0, item.remaining_grams - grams)
        if item.remaining_grams == 0:
            item.status = "finished"
    await session.commit()
    await session.refresh(item)
    return item


async def get_random_tea(session: AsyncSession, user_id: int) -> TeaCollection | None:
    from sqlalchemy.sql.expression import func
    res = await session.execute(
        select(TeaCollection)
        .where(TeaCollection.user_id == user_id, TeaCollection.status == "active")
        .order_by(func.random())
        .limit(1)
    )
    return res.scalar_one_or_none()


# ---------- Коллекция посуды ----------

async def add_teaware_item(session: AsyncSession, **fields) -> TeawareItem:
    item = TeawareItem(**fields)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def get_teaware_item(session: AsyncSession, item_id: int) -> TeawareItem | None:
    res = await session.execute(
        select(TeawareItem).where(TeawareItem.id == item_id)
    )
    return res.scalar_one_or_none()


async def list_teaware_items(
    session: AsyncSession, user_id: int
) -> list[TeawareItem]:
    res = await session.execute(
        select(TeawareItem)
        .where(TeawareItem.user_id == user_id, TeawareItem.status == "active")
        .order_by(TeawareItem.created_at.desc())
    )
    return list(res.scalars().all())


async def update_teaware_item(session: AsyncSession, item_id: int, **fields) -> TeawareItem | None:
    item = await get_teaware_item(session, item_id)
    if item is None:
        return None
    for k, v in fields.items():
        setattr(item, k, v)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_teaware_item(session: AsyncSession, item_id: int) -> bool:
    item = await get_teaware_item(session, item_id)
    if item is None:
        return False
    item.status = "deleted"
    await session.commit()
    return True
