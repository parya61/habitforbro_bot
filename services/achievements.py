"""Достижения (бейджи) и их проверка после отметки привычки."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Habit
from db.queries import add_achievement, list_habits
from services.streaks import current_streak, is_scheduled
from db.queries import get_log

# Человекочитаемые описания достижений.
ACHIEVEMENTS: dict[str, str] = {
    "streak_7": "🔥 Неделя подряд",
    "streak_30": "🌟 30 дней подряд",
    "streak_100": "💎 100 дней подряд",
    "early_bird": "🌅 Ранняя пташка (выполнено до 9:00)",
    "all_done": "🎯 Все привычки за день",
}


async def check_after_log(
    session: AsyncSession, user_id: int, habit: Habit, today: date
) -> list[str]:
    """Проверяет достижения после отметки. Возвращает список НОВЫХ бейджей."""
    new_titles: list[str] = []

    # Серийные бейджи.
    streak = await current_streak(session, habit, today)
    for threshold, code in ((7, "streak_7"), (30, "streak_30"), (100, "streak_100")):
        if streak >= threshold:
            if await add_achievement(session, user_id, code, habit_id=habit.id):
                new_titles.append(ACHIEVEMENTS[code])

    # Ранняя пташка — отметка до 9 утра.
    if datetime.utcnow().hour < 9:
        if await add_achievement(session, user_id, "early_bird"):
            new_titles.append(ACHIEVEMENTS["early_bird"])

    # Все привычки за день выполнены.
    if await _all_done_today(session, user_id, today):
        if await add_achievement(session, user_id, "all_done", habit_id=None):
            new_titles.append(ACHIEVEMENTS["all_done"])

    return new_titles


async def _all_done_today(session: AsyncSession, user_id: int, today: date) -> bool:
    habits = await list_habits(session, user_id)
    scheduled = [h for h in habits if is_scheduled(h, today)]
    if not scheduled:
        return False
    for habit in scheduled:
        log = await get_log(session, habit.id, today)
        if log is None or not log.done:
            return False
    return True
