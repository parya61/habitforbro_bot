"""Напоминания и рассылки на APScheduler.

- Персональные напоминания по времени привычки.
- Утреннее сообщение со списком привычек на день.
- Вечернее напоминание тем, кто ещё не отметился.
- Еженедельный отчёт в воскресенье вечером.
- Ежемесячные итоги с топ-3 и призами VPN.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("habits-bot")

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from db.database import get_session
from db.queries import (
    get_log,
    get_prize,
    get_user_by_tg,
    list_habits,
    list_public_habits,
    list_users,
    set_prize,
    set_prize_winners,
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
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler()

    base_tz = ZoneInfo("Europe/Moscow")
    _scheduler.add_job(_morning_broadcast, CronTrigger(hour=8, minute=0, timezone=base_tz))
    _scheduler.add_job(_evening_broadcast, CronTrigger(hour=21, minute=0, timezone=base_tz))
    _scheduler.add_job(
        _weekly_report,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _check_month_end,
        CronTrigger(hour=21, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _month_start_announce,
        CronTrigger(day=1, hour=10, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _check_goal_reminders,
        CronTrigger(minute="*", timezone=base_tz),
    )
    _scheduler.add_job(
        _friday_shopping_reminder,
        CronTrigger(day_of_week="fri", hour=16, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _gift_reminder_check,
        CronTrigger(hour=10, minute=0, timezone=base_tz),
    )

    async with get_session() as session:
        for user in await list_users(session):
            for habit in await list_habits(session, user.id):
                if habit.remind_time:
                    schedule_habit_reminder(bot, habit, user)

    _scheduler.start()


def schedule_habit_reminder(bot: Bot, habit, user) -> None:
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
            return
    await _safe_send(telegram_id, "⏰ Пора: {e} {t}!".format(e=habit.emoji, t=habit.title))


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
                f"\U0001f319 Не забудь отметить: {names}\nИ загляни в дневник \U0001f4d4",
            )


async def _weekly_report() -> None:
    async with get_session() as session:
        users = await list_users(session)
        for user in users:
            stats = await user_stats(session, user.id)
            text = (
                "\U0001f4c5 <b>Итоги недели</b>\n"
                f"Выполнено: {stats.week_done}/{stats.week_planned} "
                f"({stats.week_percent}%)\n"
                f"\U0001f3c6 Рекорд серии: {stats.record_streak} дн.\n"
                f"Активных привычек: {stats.active_habits}\n\n"
                "Так держать! Новая неделя — новые серии \U0001f525"
            )
            await _safe_send(user.telegram_id, text)


async def _compute_top3(session, month_start: date, month_end: date):
    """Вычисляет топ-3 по проценту выполнения публичных привычек."""
    scores = []
    for user in await list_users(session):
        habits = await list_public_habits(session, user.id)
        if not habits:
            continue
        total_done = total_planned = 0
        for h in habits:
            d, p = await completion_rate(session, h, month_start, month_end)
            total_done += d
            total_planned += p
        rate = total_done / total_planned if total_planned > 0 else 0
        if rate > 0:
            scores.append((user, rate, total_done, total_planned))
    scores.sort(key=lambda x: (-x[1], -x[2]))
    return scores[:3]


async def _check_month_end() -> None:
    """Каждый день в 21:00 проверяет — последний ли день месяца.
    Если да — подводит итоги и постит в группу."""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day != last_day:
        return

    logger.info("PRIZE | Последний день месяца — подводим итоги")
    month_str = today.strftime("%Y-%m")
    month_start = today.replace(day=1)

    async with get_session() as session:
        prize = await get_prize(session, month_str)
        if prize and prize.winner_user_id is not None:
            logger.info("PRIZE | %s — итоги уже объявлены, пропускаем", month_str)
            return

        top3 = await _compute_top3(session, month_start, today)
        if not top3:
            logger.warning("PRIZE | %s — нет данных для топа, пропускаем", month_str)
            return

        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        places = ["1 место", "2 место", "3 место"]

        lines = [f"\U0001f3c6 <b>Итоги месяца {month_str}</b>\n"]
        winner_ids = []
        for i, (user, rate, done, planned) in enumerate(top3):
            pct = round(rate * 100)
            lines.append(
                f"{medals[i]} <b>{places[i]}</b>: {esc(display_name(user))}"
                f" — {pct}% ({done}/{planned})"
            )
            winner_ids.append(user.id)
            logger.info(
                "PRIZE | %s %s: %s (tg=%d) — %d%% (%d/%d)",
                month_str, places[i], display_name(user),
                user.telegram_id, pct, done, planned,
            )

        lines.append("\n\U0001f381 Призы — VPN Helsinki (\U0001f1eb\U0001f1ee Финляндия) на месяц!")
        lines.append("Нажми кнопку ниже, чтобы получить свой приз.")

        if not prize:
            prize = await set_prize(session, month_str, "VPN Helsinki на 1 месяц", None)

        await set_prize_winners(
            session,
            prize,
            winner_ids[0] if len(winner_ids) > 0 else None,
            winner_ids[1] if len(winner_ids) > 1 else None,
            winner_ids[2] if len(winner_ids) > 2 else None,
        )
        logger.info("PRIZE | %s — победители сохранены в БД", month_str)

        text = "\n".join(lines)

        # Всем пользователям — итоги без кнопок
        users = await list_users(session)
        for user in users:
            await _safe_send(user.telegram_id, text)
        logger.info("PRIZE | Итоги отправлены %d пользователям", len(users))

        # Победителям — персональное сообщение с кнопкой
        for i, (winner, rate, done, planned) in enumerate(top3):
            btn = InlineKeyboardButton(
                text=f"{medals[i]} Забрать приз",
                callback_data=f"claim_vpn:{month_str}:{i + 1}",
            )
            prize_markup = InlineKeyboardMarkup(inline_keyboard=[[btn]])
            await _safe_send(
                winner.telegram_id,
                f"{medals[i]} <b>Поздравляем, ты в топ-3!</b>\n"
                f"Нажми кнопку, чтобы получить VPN Helsinki:",
                markup=prize_markup,
            )
            logger.info(
                "PRIZE | Кнопка «Забрать приз» отправлена: %s (tg=%d)",
                display_name(winner), winner.telegram_id,
            )


async def _month_start_announce() -> None:
    """1-го числа в 10:00 — объявляем приз нового месяца."""
    today = date.today()
    month_str = today.strftime("%Y-%m")
    logger.info("PRIZE | Объявляем приз месяца %s", month_str)

    text = (
        f"\U0001f389 <b>Новый месяц — новый приз!</b>\n\n"
        f"\U0001f4c5 {month_str}\n"
        f"\U0001f381 Приз: <b>VPN Helsinki</b> (\U0001f1eb\U0001f1ee Финляндия) на 1 месяц\n"
        f"\U0001f310 WireGuard, до 18 Мбит/с, безлимитный трафик\n\n"
        f"Топ-3 по выполнению публичных привычек получат персональный VPN!\n"
        f"Старайтесь и не пропускайте привычки \U0001f4aa"
    )

    async with get_session() as session:
        prize = await get_prize(session, month_str)
        if not prize:
            await set_prize(session, month_str, "VPN Helsinki \U0001f1eb\U0001f1ee на 1 месяц", None)
            logger.info("PRIZE | Запись приза создана в БД: %s", month_str)

        users = await list_users(session)
        for user in users:
            await _safe_send(user.telegram_id, text)
        logger.info("PRIZE | Анонс отправлен %d пользователям", len(users))


async def _check_goal_reminders() -> None:
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from db.models import Goal

    now = datetime.utcnow()
    async with get_session() as session:
        res = await session.execute(
            select(Goal)
            .options(joinedload(Goal.user))
            .where(
                Goal.remind_at.isnot(None),
                Goal.remind_at <= now,
                Goal.status == "active",
            )
        )
        goals = list(res.scalars().all())
        for goal in goals:
            await _safe_send(
                goal.user.telegram_id,
                f"⏰ Напоминание о цели:\n\n<b>{esc(goal.title)}</b>",
            )
            goal.remind_at = None
        if goals:
            await session.commit()


async def _gift_reminder_check() -> None:
    from datetime import date as date_cls

    from db.gift_queries import list_persons
    from services.gift import (
        ALERT_DAYS,
        REL_LABELS,
        days_label,
        upcoming_birthdays,
        upcoming_holidays,
    )

    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            return
        today = date_cls.today()
        persons = await list_persons(session, user.id)
        bdays = upcoming_birthdays(persons, today, days_ahead=ALERT_DAYS)
        holidays = upcoming_holidays(today, days_ahead=ALERT_DAYS)

        alerts = []
        for hdate, hname, delta in holidays:
            if delta in (21, 14, 7, 3, 1, 0):
                alerts.append(f"{hname} — {days_label(delta)}")

        for person, bdate, delta, age in bdays:
            if delta in (21, 14, 7, 3, 1, 0):
                rel = REL_LABELS.get(person.rel_type, "")
                rel_str = f" ({rel})" if rel else ""
                gifts = person.gifts or []
                ideas = [g for g in gifts if g.status == "idea"]
                hint = f"\n  💡 Идеи: {', '.join(g.title for g in ideas[:3])}" if ideas else ""
                alerts.append(
                    f"🎂 {person.name}{rel_str} — {age} лет, {days_label(delta)}{hint}"
                )

        if alerts:
            text = "🎁 <b>Напоминание о подарках</b>\n\n" + "\n".join(alerts)
            await _safe_send(user.telegram_id, text)


async def _friday_shopping_reminder() -> None:
    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            return
        from db.grocery_queries import count_items, group_by_store, list_due_items
        from services.grocery import ensure_seeded, format_shopping_list

        await ensure_seeded(session, user.id)
        if await count_items(session, user.id) == 0:
            return
        due = await list_due_items(session, user.id)
        if not due:
            return
        grouped = group_by_store(due)
        text = format_shopping_list(grouped, len(due))
        await _safe_send(
            user.telegram_id,
            f"🛒 <b>Пятница! Пора составить список покупок</b>\n\n{text}"
            f"\nОткрой /finance → Продукты, чтобы отметить купленное.",
        )


async def _safe_send(chat_id: int, text: str, markup=None) -> None:
    if _bot is None:
        return
    try:
        await _bot.send_message(chat_id, text, reply_markup=markup)
    except Exception:
        pass
