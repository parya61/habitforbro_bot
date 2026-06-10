"""Тесты логики серий, расписания и процента выполнения (services/streaks.py)."""
from __future__ import annotations

from datetime import date, timedelta

from db.models import Habit
from services.streaks import (
    FREEZE_PER_MONTH,
    _streak_flexible,
    best_streak,
    completion_rate,
    current_streak,
    is_scheduled,
    parse_weekdays,
)
from tests.conftest import add_done, make_habit

# Фиксированная «сегодня» — будний день (понедельник 2026-06-08).
TODAY = date(2026, 6, 8)


def d(offset: int) -> date:
    """Дата на offset дней назад от TODAY."""
    return TODAY - timedelta(days=offset)


# ---------- Чистые функции ----------

def test_parse_weekdays():
    assert parse_weekdays("0,1,4") == {0, 1, 4}
    assert parse_weekdays(None) == set()
    assert parse_weekdays("") == set()
    assert parse_weekdays("0, 2 ,x") == {0, 2}


def test_is_scheduled_daily():
    h = Habit(frequency="daily")
    assert is_scheduled(h, TODAY) is True


def test_is_scheduled_weekdays():
    # TODAY — понедельник (weekday 0).
    h = Habit(frequency="weekdays", freq_value="0,2")  # Пн, Ср
    assert is_scheduled(h, TODAY) is True          # понедельник
    assert is_scheduled(h, TODAY + timedelta(days=1)) is False  # вторник
    assert is_scheduled(h, TODAY + timedelta(days=2)) is True   # среда


def test_is_scheduled_times_per_week_is_flexible():
    h = Habit(frequency="times_per_week", freq_value="3")
    # Любой день считается допустимым.
    for i in range(7):
        assert is_scheduled(h, TODAY + timedelta(days=i)) is True


def test_streak_flexible_within_gap():
    done = {d(0), d(7), d(14)}  # ровно по 7 дней — разрывы допустимы
    assert _streak_flexible(done, TODAY) == 3


def test_streak_flexible_breaks_on_big_gap():
    done = {d(0), d(8)}  # разрыв 8 дней рвёт серию
    assert _streak_flexible(done, TODAY) == 1


def test_streak_flexible_stale_returns_zero():
    done = {d(10)}  # последнее выполнение старше недели
    assert _streak_flexible(done, TODAY) == 0


# ---------- current_streak (daily) ----------

async def test_current_streak_consecutive(session):
    h = await make_habit(session, frequency="daily")
    await add_done(session, h.id, [d(0), d(1), d(2)])
    assert await current_streak(session, h, TODAY) == 3


async def test_current_streak_today_not_done_keeps_streak(session):
    h = await make_habit(session, frequency="daily")
    # Сегодня не отмечено, но вчера и позавчера — да. День не окончен → серия живёт.
    await add_done(session, h.id, [d(1), d(2)])
    assert await current_streak(session, h, TODAY) == 2


async def test_current_streak_freeze_saves_one_gap(session):
    h = await make_habit(session, frequency="daily")
    # Пропущен d(3); остальные подряд. Заморозка не должна обнулить серию.
    await add_done(session, h.id, [d(0), d(1), d(2), d(4), d(5)])
    assert await current_streak(session, h, TODAY) == 5


async def test_current_streak_breaks_after_freeze_limit(session):
    h = await make_habit(session, frequency="daily")
    # 3 пропуска подряд (d1,d2,d3) превышают FREEZE_PER_MONTH=2 → серия = 1 (только сегодня).
    assert FREEZE_PER_MONTH == 2
    await add_done(session, h.id, [d(0), d(4)])
    assert await current_streak(session, h, TODAY) == 1


async def test_current_streak_empty(session):
    h = await make_habit(session, frequency="daily")
    assert await current_streak(session, h, TODAY) == 0


# ---------- current_streak (times_per_week через БД) ----------

async def test_current_streak_times_per_week(session):
    h = await make_habit(session, frequency="times_per_week", freq_value="3")
    await add_done(session, h.id, [d(0), d(6), d(12)])
    assert await current_streak(session, h, TODAY) == 3


# ---------- best_streak ----------

async def test_best_streak_picks_longest_run(session):
    h = await make_habit(session, frequency="daily")
    # Два прогона: 2 подряд и 3 подряд (с разрывом). best = 3, без учёта заморозки.
    await add_done(session, h.id, [d(10), d(9), d(5), d(4), d(3)])
    assert await best_streak(session, h, TODAY) == 3


async def test_best_streak_empty(session):
    h = await make_habit(session, frequency="daily")
    assert await best_streak(session, h, TODAY) == 0


# ---------- completion_rate ----------

async def test_completion_rate_weekdays(session):
    # Привычка по Пн (0) и Ср (2). Неделя Пн..Вс → запланировано 2 дня.
    h = await make_habit(session, frequency="weekdays", freq_value="0,2")
    start = TODAY                      # понедельник
    end = TODAY + timedelta(days=6)    # воскресенье
    await add_done(session, h.id, [TODAY])  # выполнен только понедельник
    done, planned = await completion_rate(session, h, start, end)
    assert (done, planned) == (1, 2)


async def test_completion_rate_daily_full(session):
    h = await make_habit(session, frequency="daily")
    start, end = d(2), d(0)
    await add_done(session, h.id, [d(0), d(1), d(2)])
    done, planned = await completion_rate(session, h, start, end)
    assert (done, planned) == (3, 3)
