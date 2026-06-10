"""Логика серий (streak) и статистики выполнения привычек.

Учитываются:
- периодичность (каждый день / по дням недели / N раз в неделю);
- «заморозка» — до 2 пропусков в месяц без обнуления серии.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Habit
from db.queries import get_logs_range

# Сколько пропусков в месяц можно «заморозить» (не обнуляя серию).
FREEZE_PER_MONTH = 2


def parse_weekdays(freq_value: str | None) -> set[int]:
    """Превращает '0,1,4' в множество {0,1,4} (пн=0)."""
    if not freq_value:
        return set()
    return {int(x) for x in freq_value.split(",") if x.strip().isdigit()}


def is_scheduled(habit: Habit, day: date) -> bool:
    """Запланирована ли привычка на конкретный день.

    Для 'times_per_week' любой день считается допустимым (гибкий график),
    поэтому пропуск отдельного дня не штрафуется.
    """
    if habit.frequency == "daily":
        return True
    if habit.frequency == "weekdays":
        return day.weekday() in parse_weekdays(habit.freq_value)
    # times_per_week — гибкий график.
    return True


async def _done_dates(
    session: AsyncSession, habit: Habit, start: date, end: date
) -> set[date]:
    logs = await get_logs_range(session, habit.id, start, end)
    return {log.log_date for log in logs if log.done}


async def current_streak(
    session: AsyncSession, habit: Habit, today: date | None = None
) -> int:
    """Текущая серия в днях.

    Для daily/weekdays идём назад по запланированным дням: выполненный —
    +1, пропуск гасим «заморозкой» (до FREEZE_PER_MONTH в месяц), иначе серия
    прерывается. Сегодняшний невыполненный день серию не рвёт (день не окончен).

    Для times_per_week считаем подряд идущие выполненные дни, допуская разрывы
    не больше недели между ними.
    """
    today = today or date.today()
    # Берём логи за последние ~400 дней — этого хватает для любой серии.
    window_start = today - timedelta(days=400)
    done = await _done_dates(session, habit, window_start, today)

    if habit.frequency == "times_per_week":
        return _streak_flexible(done, today)

    streak = 0
    freeze_used_by_month: dict[tuple[int, int], int] = {}
    day = today
    while day >= window_start:
        if not is_scheduled(habit, day):
            day -= timedelta(days=1)
            continue
        if day in done:
            streak += 1
        else:
            if day == today:
                # Сегодня ещё можно выполнить — не считаем пропуском.
                day -= timedelta(days=1)
                continue
            key = (day.year, day.month)
            used = freeze_used_by_month.get(key, 0)
            if used < FREEZE_PER_MONTH:
                freeze_used_by_month[key] = used + 1  # «замораживаем» пропуск
            else:
                break
        day -= timedelta(days=1)
    return streak


def _streak_flexible(done: set[date], today: date) -> int:
    """Серия для гибкого графика (N раз в неделю): подряд идущие выполненные
    дни с разрывами не больше 7 дней."""
    dates = sorted(done, reverse=True)
    if not dates:
        return 0
    # Серия активна, только если последнее выполнение не старше недели.
    if (today - dates[0]).days > 7:
        return 0
    streak = 1
    for prev, cur in zip(dates, dates[1:]):
        if (prev - cur).days <= 7:
            streak += 1
        else:
            break
    return streak


async def best_streak(
    session: AsyncSession, habit: Habit, today: date | None = None
) -> int:
    """Лучшая (максимальная) серия за всю историю привычки."""
    today = today or date.today()
    window_start = today - timedelta(days=400)
    done = await _done_dates(session, habit, window_start, today)
    if not done:
        return 0

    if habit.frequency == "times_per_week":
        best = cur = 0
        dates = sorted(done)
        prev: date | None = None
        for d in dates:
            if prev is None or (d - prev).days <= 7:
                cur += 1
            else:
                cur = 1
            best = max(best, cur)
            prev = d
        return best

    best = cur = 0
    day = window_start
    while day <= today:
        if is_scheduled(habit, day):
            if day in done:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        day += timedelta(days=1)
    return best


async def completion_rate(
    session: AsyncSession, habit: Habit, start: date, end: date
) -> tuple[int, int]:
    """Возвращает (выполнено, запланировано) за период [start, end]."""
    done = await _done_dates(session, habit, start, end)
    scheduled = 0
    done_count = 0
    day = start
    while day <= end:
        if is_scheduled(habit, day):
            scheduled += 1
            if day in done:
                done_count += 1
        day += timedelta(days=1)
    return done_count, scheduled
