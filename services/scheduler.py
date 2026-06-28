"""Напоминания и рассылки на APScheduler.

- Персональные напоминания по времени привычки.
- Утреннее сообщение со списком привычек на день.
- Вечернее напоминание тем, кто ещё не отметился.
- Еженедельный отчёт в воскресенье вечером.
"""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db.database import get_session
from db.queries import (
    get_log,
    get_prize,
    get_user_by_tg,
    list_habits,
    list_public_habits,
    list_users,
    set_prize_winner,
)
from services.stats import user_stats
from services.streaks import completion_rate, is_scheduled
from utils import display_name, esc

_scheduler: AsyncIOScheduler | None = None
_bot: Bot | None = None


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Europe/Moscow")


async def setup_scheduler(bot: Bot) -> None:
    """Создаёт планировщик, регистрирует общие задачи и напоминания привычек."""
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler()

    # Общие рассылки (время в Europe/Moscow как база; индивидуальная фильтрация в задачах).
    base_tz = ZoneInfo("Europe/Moscow")
    _scheduler.add_job(_morning_broadcast, CronTrigger(hour=8, minute=0, timezone=base_tz))
    _scheduler.add_job(_evening_broadcast, CronTrigger(hour=21, minute=0, timezone=base_tz))
    _scheduler.add_job(
        _weekly_report,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _monthly_prize_winner,
        CronTrigger(day=1, hour=0, minute=5, timezone=base_tz),
    )

    # Персональные напоминания по каждой активной привычке с указанным временем.
    async with get_session() as session:
        for user in await list_users(session):
            for habit in await list_habits(session, user.id):
                if habit.remind_time:
                    schedule_habit_reminder(bot, habit, user)

    _scheduler.start()


def schedule_habit_reminder(bot: Bot, habit, user) -> None:
    """Регистрирует (или обновляет) напоминание для конкретной привычки."""
    if _scheduler is None or not habit.remind_time:
        return
    hour, minute = (int(x) for x in habit.remind_time.split(":"))
    job_id = f"habit_{habit.id}"
    _scheduler.add_job(
        _habit_reminder,
        CronTrigger(hour=hour, minute=minute, timezone=_tz(user.timezone)),
        args=[user.telegram_id, habit.id],
        id=job_id,
        replace_existing=True,
    )


def remove_habit_reminder(habit_id: int) -> None:
    """Снимает напоминание (например, при архивации привычки)."""
    if _scheduler is None:
        return
    job = _scheduler.get_job(f"habit_{habit_id}")
    if job:
        job.remove()


async def _habit_reminder(telegram_id: int, habit_id: int) -> None:
    async with get_session() as session:
        from db.queries import get_habit

        habit = await get_habit(session, habit_id)
        if not habit or habit.status != "active":
            return
        today = date.today()
        if not is_scheduled(habit, today):
            return
        log = await get_log(session, habit_id, today)
        if log and log.done:
            return  # уже выполнено сегодня
    await _safe_send(telegram_id, f"⏰ Пора: {habit.emoji} {habit.title}!")


async def _morning_broadcast() -> None:
    async with get_session() as session:
        users = await list_users(session)
        for user in users:
            if not user.morning_enabled:
                continue
            today = date.today()
            habits = [h for h in await list_habits(session, user.id) if is_scheduled(h, today)]
            if not habits:
                continue
            lines = ["☀️ <b>Доброе утро!</b> Привычки на сегодня:"]
            for h in habits:
                lines.append(f"⬜ {h.emoji} {h.title}")
            await _safe_send(user.telegram_id, "\n".join(lines))


async def _evening_broadcast() -> None:
    async with get_session() as session:
        users = await list_users(session)
        for user in users:
            if not user.evening_enabled:
                continue
            today = date.today()
            habits = [h for h in await list_habits(session, user.id) if is_scheduled(h, today)]
            pending = []
            for h in habits:
                log = await get_log(session, h.id, today)
                if not (log and log.done):
                    pending.append(h)
            if not pending:
                continue
            names = ", ".join(f"{h.emoji} {h.title}" for h in pending)
            await _safe_send(
                user.telegram_id,
                f"🌙 Не забудь отметить: {names}\nИ загляни в дневник 📔",
            )


async def _weekly_report() -> None:
    async with get_session() as session:
        users = await list_users(session)
        for user in users:
            stats = await user_stats(session, user.id)
            text = (
                "📅 <b>Итоги недели</b>\n"
                f"Выполнено: {stats.week_done}/{stats.week_planned} "
                f"({stats.week_percent}%)\n"
                f"🏆 Рекорд серии: {stats.record_streak} дн.\n"
                f"Активных привычек: {stats.active_habits}\n\n"
                "Так держать! Новая неделя — новые серии 🔥"
            )
            await _safe_send(user.telegram_id, text)


async def _monthly_prize_winner() -> None:
    today = date.today()
    last_day = today - timedelta(days=1)
    month_str = last_day.strftime("%Y-%m")
    month_start = last_day.replace(day=1)

    async with get_session() as session:
        prize = await get_prize(session, month_str)
        if not prize or prize.winner_user_id is not None:
            return

        best_user = None
        best_rate = -1.0
        for user in await list_users(session):
            habits = await list_public_habits(session, user.id)
            if not habits:
                continue
            total_done = total_planned = 0
            for h in habits:
                d, p = await completion_rate(session, h, month_start, last_day)
                total_done += d
                total_planned += p
            rate = total_done / total_planned if total_planned > 0 else 0
            if rate > best_rate:
                best_rate = rate
                best_user = user

        if not best_user or best_rate <= 0:
            return

        await set_prize_winner(session, prize, best_user.id)

        text = (
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"Ты победитель месяца ({month_str}) "
            f"с результатом {round(best_rate * 100)}%!\n\n"
            f"🎁 Твой приз: {prize.description}"
        )
        if prize.prize_code:
            text += f"\n\n🔑 Код: <tg-spoiler>{prize.prize_code}</tg-spoiler>"
        await _safe_send(best_user.telegram_id, text)

        winner_name = display_name(best_user)
        for user in await list_users(session):
            if user.id != best_user.id:
                await _safe_send(
                    user.telegram_id,
                    f"🏆 Победитель месяца ({month_str}): "
                    f"{esc(winner_name)} с результатом {round(best_rate * 100)}%!",
                )


async def _safe_send(telegram_id: int, text: str) -> None:
    """Отправка с защитой от ошибок (пользователь заблокировал бота и т.п.)."""
    if _bot is None:
        return
    try:
        await _bot.send_message(telegram_id, text)
    except Exception:
        pass
