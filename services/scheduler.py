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
from db.queries import get_log, get_user_by_tg, list_habits, list_users
from services.stats import user_stats
from services.streaks import is_scheduled

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


async def _safe_send(telegram_id: int, text: str) -> None:
    """Отправка с защитой от ошибок (пользователь заблокировал бота и т.п.)."""
    if _bot is None:
        return
    try:
        await _bot.send_message(telegram_id, text)
    except Exception:
        pass
