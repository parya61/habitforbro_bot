"""Сводная статистика пользователя и текстовый трекер привычки."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Habit
from db.queries import get_logs_range, list_habits
from services.streaks import (
    best_streak,
    completion_rate,
    current_streak,
    is_scheduled,
)


@dataclass
class UserStats:
    active_habits: int
    week_done: int
    week_planned: int
    month_done: int
    month_planned: int
    total_marks: int
    record_streak: int

    @property
    def week_percent(self) -> int:
        return round(100 * self.week_done / self.week_planned) if self.week_planned else 0

    @property
    def month_percent(self) -> int:
        return (
            round(100 * self.month_done / self.month_planned)
            if self.month_planned
            else 0
        )


async def user_stats(session: AsyncSession, user_id: int) -> UserStats:
    today = date.today()
    week_start = today - timedelta(days=6)
    month_start = today - timedelta(days=29)

    habits = await list_habits(session, user_id)
    week_done = week_planned = month_done = month_planned = 0
    total_marks = 0
    record = 0

    for habit in habits:
        wd, wp = await completion_rate(session, habit, week_start, today)
        md, mp = await completion_rate(session, habit, month_start, today)
        week_done += wd
        week_planned += wp
        month_done += md
        month_planned += mp
        total_marks += md  # всего отметок за месяц как ориентир активности
        record = max(record, await best_streak(session, habit, today))

    return UserStats(
        active_habits=len(habits),
        week_done=week_done,
        week_planned=week_planned,
        month_done=month_done,
        month_planned=month_planned,
        total_marks=total_marks,
        record_streak=record,
    )


async def render_tracker(
    session: AsyncSession, habit: Habit, days: int = 30
) -> str:
    """Текстовый трекер за последние N дней, по неделям (пн→вс)."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    logs = await get_logs_range(session, habit.id, start, today)
    done = {log.log_date for log in logs if log.done}

    # Выравниваем начало на понедельник для аккуратной сетки.
    grid_start = start - timedelta(days=start.weekday())
    lines = ["Пн Вт Ср Чт Пт Сб Вс"]
    row: list[str] = []
    day = grid_start
    while day <= today:
        if day < start:
            cell = "  "  # вне диапазона
        elif day in done:
            cell = "✅"
        elif is_scheduled(habit, day):
            cell = "❌"
        else:
            cell = "▫️"  # день не по расписанию
        row.append(cell)
        if day.weekday() == 6:  # воскресенье — конец строки
            lines.append(" ".join(row))
            row = []
        day += timedelta(days=1)
    if row:
        lines.append(" ".join(row))

    cur = await current_streak(session, habit, today)
    best = await best_streak(session, habit, today)
    lines.append("")
    lines.append(f"🔥 Текущая серия: {cur} | 🏆 Рекорд: {best}")
    return "\n".join(lines)
