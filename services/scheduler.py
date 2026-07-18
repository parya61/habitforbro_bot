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
from services.streaks import completion_rate, current_streak, is_scheduled
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
    _scheduler.add_job(
        _feed_check,
        CronTrigger(hour=6, minute=0, timezone=base_tz),
    )
    _scheduler.add_job(
        _unified_morning_brief,
        CronTrigger(hour=7, minute=30, timezone=base_tz),
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
            # админ получает единый бриф в 07:30 — без дубля в 08:00
            if user.telegram_id == config.admin_id:
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


MOOD_SCORE = {"😀": 5, "🙂": 4, "😐": 3, "😴": 2, "😔": 2, "😢": 1}
WEEKDAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


async def _compute_behavior_features(session, user) -> str:
    """Поведенческие закономерности за 28 дней, посчитанные кодом.

    LLM получает готовые цифры и интерпретирует — но не вычисляет их сам.
    """
    from db.queries import list_diary_entries

    habits = [h for h in await list_habits(session, user.id) if h.status == "active"]
    if not habits:
        return ""
    today = date.today()

    day_stats: dict[date, tuple[int, int]] = {}
    habit_miss: dict[int, int] = {h.id: 0 for h in habits}
    habit_title = {h.id: h.title for h in habits}
    for i in range(1, 29):
        d = today - timedelta(days=i)
        planned = [h for h in habits if is_scheduled(h, d)]
        if not planned:
            continue
        done = 0
        for h in planned:
            log = await get_log(session, h.id, d)
            if log and log.done:
                done += 1
            else:
                habit_miss[h.id] += 1
        day_stats[d] = (done, len(planned))

    lines = []

    wd: dict[int, list[int]] = {i: [0, 0] for i in range(7)}
    for d, (done, planned) in day_stats.items():
        wd[d.weekday()][0] += done
        wd[d.weekday()][1] += planned
    wd_parts = [
        f"{WEEKDAY_NAMES[i]} {round(100 * wd[i][0] / wd[i][1])}%"
        for i in range(7) if wd[i][1]
    ]
    if wd_parts:
        lines.append("Выполнение по дням недели (28 дн): " + ", ".join(wd_parts))
        worst = min(
            (i for i in range(7) if wd[i][1]),
            key=lambda i: wd[i][0] / wd[i][1],
        )
        lines.append(f"Самый слабый день: {WEEKDAY_NAMES[worst]}")

    entries = await list_diary_entries(session, user.id, limit=40)
    good, low = [], []
    for e in entries:
        score = MOOD_SCORE.get(e.mood or "")
        st = day_stats.get(e.entry_date)
        if score is None or not st or st[1] == 0:
            continue
        pct = st[0] / st[1]
        if score >= 4:
            good.append(pct)
        elif score <= 2:
            low.append(pct)
    if good and low:
        lines.append(
            f"Настроение и привычки: в дни хорошего настроения выполнение "
            f"{round(100 * sum(good) / len(good))}%, в дни плохого — "
            f"{round(100 * sum(low) / len(low))}%"
        )

    streak_lines = []
    for h in habits:
        s = await current_streak(session, h)
        if s >= 7:
            streak_lines.append(f"{h.title} — {s} дн")
    if streak_lines:
        lines.append("Серии под защитой (не потерять!): " + "; ".join(streak_lines))

    misses = sorted(habit_miss.items(), key=lambda kv: -kv[1])[:2]
    miss_parts = [f"{habit_title[hid]} ({n} пропусков)" for hid, n in misses if n > 0]
    if miss_parts:
        lines.append("Чаще всего пропускается: " + ", ".join(miss_parts))

    return "\n".join(lines)


async def _weekly_report() -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from services.ai_analytics import SYSTEM_PROMPT, ask_deepseek, build_user_context

    async with get_session() as session:
        users = await list_users(session)
        for user in users:
            stats = await user_stats(session, user.id)

            context = await build_user_context(session, user)
            features = await _compute_behavior_features(session, user)

            prompt = (
                "Ты — Керя, персональный ассистент. "
                "Ниже данные пользователя за неделю: привычки, дневник, цели, серии.\n\n"
                f"{context}\n\n"
                "ВЫЧИСЛЕННЫЕ ЗАКОНОМЕРНОСТИ (точные цифры, доверяй им, "
                "не пересчитывай):\n"
                f"{features}\n\n"
                "Сделай воскресный разбор недели:\n"
                "1. Что получилось хорошо — похвали конкретно\n"
                "2. Где провал или спад — используй закономерности выше "
                "(слабый день недели, связь с настроением, пропуски)\n"
                "3. Дай 2-3 конкретных совета на следующую неделю, "
                "опираясь на цифры, а не на общие слова\n"
                "4. Если есть серии под защитой — предупреди о рисках\n"
                "Формат: коротко, по-дружески, на русском. До 1500 символов."
            )

            resp = await ask_deepseek(
                config.deepseek_api_key,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

            if resp.ok and resp.text:
                text = f"\U0001f4c5 <b>Итоги недели от Кери</b>\n\n{resp.text}"
            else:
                text = (
                    "\U0001f4c5 <b>Итоги недели</b>\n"
                    f"Выполнено: {stats.week_done}/{stats.week_planned} "
                    f"({stats.week_percent}%)\n"
                    f"\U0001f3c6 Рекорд серии: {stats.record_streak} дн.\n"
                    f"Активных привычек: {stats.active_habits}\n\n"
                    "Так держать! Новая неделя — новые серии \U0001f525"
                )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="\U0001f4ac Задать вопрос Кере",
                    callback_data="analytics:weekly_start",
                )],
            ])
            await _safe_send(user.telegram_id, text, markup=kb)


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


async def _feed_check() -> None:
    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            return
        from services.feed_aggregator import run_feed_check
        try:
            results = await run_feed_check(session, user.id)
            total = sum(results.values())
            if total:
                logger.info("FEED | Collected %d new items (tg=%d, yt=%d)",
                            total, results.get("telegram", 0), results.get("youtube", 0))
        except Exception as exc:
            logger.error("FEED | Check failed: %s", exc)


async def _mlsec_morning_digest() -> None:
    from datetime import datetime, timedelta

    from db.feed_queries import recent_items
    from services.ai_analytics import ask_deepseek

    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            return

        yesterday = datetime.utcnow() - timedelta(hours=24)
        items = await recent_items(session, user.id, limit=50)
        fresh = [
            it for it in items
            if it.published_at and it.published_at >= yesterday
        ]

        if not fresh:
            await _safe_send(
                config.admin_id,
                "📡 <b>Утренняя сводка MLSecOps</b>\n\n"
                "За последние 24 часа ничего нового и интересного "
                "по твоим подпискам не появилось. Спокойное утро ☕",
            )
            return

        digest_parts = []
        for it in fresh:
            src = it.source.title if it.source else "?"
            title = (it.title or "")[:120]
            text_preview = (it.text or "")[:400]
            url = it.url or ""
            digest_parts.append(
                f"[{src}] {title}\n{text_preview}\n{url}"
            )

        raw_feed = "\n---\n".join(digest_parts)

        prompt = (
            "Ты — ИБ-аналитик. Ниже — посты из Telegram-каналов и YouTube "
            "за последние 24 часа по темам: MLSecOps, ML Security, AI Safety, "
            "ИБ, DevSecOps, машинное обучение.\n\n"
            "Составь краткую утреннюю сводку для ИБ-инженера "
            "(специализация MLSecOps, магистратура ВШЭ).\n"
            "Формат:\n"
            "- Заголовок новости + 1-2 предложения суть\n"
            "- Если есть ссылка — добавь\n"
            "- Выдели самое важное/практически полезное\n"
            "- Если ничего реально ценного — так и скажи\n"
            "- На русском, коротко (до 2000 символов)\n\n"
            f"Посты ({len(fresh)} шт.):\n\n{raw_feed[:6000]}"
        )

        resp = await ask_deepseek(
            config.deepseek_api_key,
            [{"role": "user", "content": prompt}],
        )

        if resp.ok and resp.text:
            msg = f"📡 <b>Утренняя сводка MLSecOps</b>\n\n{resp.text}"
        else:
            lines = []
            for it in fresh[:10]:
                src = it.source.title if it.source else "?"
                title = (it.title or "")[:80]
                lines.append(f"• [{src}] {title}")
            msg = (
                f"📡 <b>Утренняя сводка</b>\n\n"
                f"За 24ч — {len(fresh)} новых постов:\n"
                + "\n".join(lines)
            )

        await _safe_send(config.admin_id, msg)
        logger.info("DIGEST | Sent morning MLSecOps digest (%d items)", len(fresh))


async def _hh_vacancy_monitor() -> None:
    from services.hh_monitor import check_vacancies, format_vacancies

    try:
        vacancies = await check_vacancies()
        msg = format_vacancies(vacancies)
        await _safe_send(config.admin_id, msg)
        logger.info("HH | Sent vacancy digest (%d new)", len(vacancies))
    except Exception as exc:
        logger.error("HH | Monitor failed: %s", exc)


async def _habit_risks(session, user, today: date) -> list[str]:
    """Привычки под риском срыва сегодня: слабый день недели + серия на кону.

    Эвристика вместо ML: провал этого дня недели за 28 дн >= 40%,
    или 2+ пропуска за последние 7 дней при живой серии >= 5.
    """
    habits = [
        h for h in await list_habits(session, user.id)
        if h.status == "active" and is_scheduled(h, today)
    ]
    scored = []
    for h in habits:
        wd_planned = wd_done = recent_miss = 0
        for i in range(1, 29):
            d = today - timedelta(days=i)
            if not is_scheduled(h, d):
                continue
            log = await get_log(session, h.id, d)
            done = bool(log and log.done)
            if d.weekday() == today.weekday():
                wd_planned += 1
                wd_done += int(done)
            if i <= 7 and not done:
                recent_miss += 1

        streak = await current_streak(session, h)
        wd_fail = 1 - wd_done / wd_planned if wd_planned >= 2 else 0

        if wd_fail >= 0.4 and streak >= 3:
            pct = round(100 * (1 - wd_fail))
            scored.append((
                wd_fail * streak,
                f"{h.emoji} {h.title}: {WEEKDAY_NAMES[today.weekday()]} — "
                f"слабый день ({pct}% выполнения), серия {streak} дн на кону",
            ))
        elif recent_miss >= 2 and streak >= 5:
            scored.append((
                0.3 * streak,
                f"{h.emoji} {h.title}: {recent_miss} пропуска за неделю, "
                f"серия {streak} дн под угрозой",
            ))

    # навигатор, а не надзиратель: максимум 3 самых ценных предупреждения
    scored.sort(key=lambda x: -x[0])
    return [text for _, text in scored[:3]]


async def _unified_morning_brief() -> None:
    """Единый утренний бриф для админа: привычки, ДР, финансы, MLSecOps, вакансии.

    Заменяет собой отдельные рассылки 07:30 (дайджест) и 07:50 (вакансии),
    а утренний список привычек 08:00 для админа отключён.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from db.feed_queries import recent_items
    from db.gift_queries import list_persons
    from db.models import FinTransaction
    from services.ai_analytics import ask_deepseek
    from services.gift import days_label, upcoming_birthdays

    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            return
        today = date.today()
        parts = ["☀️ <b>Утренний бриф</b>"]

        habits = [h for h in await list_habits(session, user.id) if is_scheduled(h, today)]
        if habits:
            parts.append(
                "\n<b>Привычки:</b> " + ", ".join(f"{h.emoji} {h.title}" for h in habits)
            )

        risks = await _habit_risks(session, user, today)
        if risks:
            parts.append("\n⚡ <b>Риски дня:</b>\n" + "\n".join(f"• {r}" for r in risks))

        persons = await list_persons(session, user.id)
        bdays = upcoming_birthdays(persons, today, days_ahead=14)
        if bdays:
            lines = ["\n\U0001f382 <b>Дни рождения (14 дней):</b>"]
            for person, bdate, delta, age in bdays:
                gifts = person.gifts or []
                ideas = [g for g in gifts if g.status == "idea"]
                given = [g for g in gifts if g.status in ("bought", "given")]
                if given:
                    gift_mark = " — 🎁 подарок готов"
                elif ideas:
                    idea_strs = []
                    for g in ideas[:2]:
                        price = f" ~{g.price_estimate:,.0f}₽".replace(",", " ") \
                            if g.price_estimate else ""
                        idea_strs.append(f"{g.title}{price}")
                    gift_mark = f" — 💡 идеи: {', '.join(idea_strs)}"
                else:
                    gift_mark = " — ⚠️ <b>подарок не выбран!</b>"
                lines.append(
                    f"• {person.name} — {days_label(delta)} ({age} лет){gift_mark}"
                )
            parts.append("\n".join(lines))

        from db.models import FinCategory

        month_start = today.replace(day=1)
        res = await session.execute(
            select(func.sum(FinTransaction.amount))
            .outerjoin(FinCategory, FinCategory.id == FinTransaction.category_id)
            .where(
                FinTransaction.user_id == user.id,
                FinTransaction.tx_type == "expense",
                FinTransaction.tx_date >= month_start,
                # переводы между своими счетами — не расход
                (FinCategory.name.is_(None)) | (FinCategory.name != "Переводы"),
            )
        )
        spent = res.scalar() or 0
        res = await session.execute(
            select(func.sum(FinTransaction.amount))
            .outerjoin(FinCategory, FinCategory.id == FinTransaction.category_id)
            .where(
                FinTransaction.user_id == user.id,
                FinTransaction.tx_type == "income",
                FinTransaction.tx_date >= month_start,
                (FinCategory.name.is_(None)) | (FinCategory.name != "Переводы"),
            )
        )
        earned = res.scalar() or 0
        if spent or earned:
            spent_str = f"{spent:,.0f}".replace(",", " ")
            free_str = f"{earned - spent:,.0f}".replace(",", " ")
            parts.append(
                f"\n\U0001f4b0 Расходы месяца: {spent_str} ₽ | "
                f"свободный остаток: {free_str} ₽"
            )

        yesterday = datetime.utcnow() - timedelta(hours=24)
        items = await recent_items(session, user.id, limit=50)
        fresh = [it for it in items if it.published_at and it.published_at >= yesterday]
        if fresh:
            digest_parts = []
            for it in fresh:
                src = it.source.title if it.source else "?"
                title = (it.title or "")[:100]
                preview = (it.text or "")[:300]
                digest_parts.append(f"[{src}] {title}\n{preview}\n{it.url or ''}")
            prompt = (
                "Сводка для ИБ-инженера (MLSecOps). Ниже посты за 24ч. "
                "Выбери только реально полезное, 3-5 пунктов, каждый — заголовок "
                "+ 1 предложение + ссылка. До 800 символов. Если ничего ценного — "
                "одна строка 'ничего важного'. На русском.\n\n"
                + "\n---\n".join(digest_parts)[:5000]
            )
            resp = await ask_deepseek(
                config.deepseek_api_key,
                [{"role": "user", "content": prompt}],
            )
            if resp.ok and resp.text:
                parts.append(f"\n\U0001f4e1 <b>MLSecOps:</b>\n{resp.text}")
            else:
                parts.append(f"\n\U0001f4e1 За сутки {len(fresh)} новых постов в подписках")
        else:
            parts.append("\n\U0001f4e1 MLSecOps: за сутки тихо ☕")

        if today.toordinal() % 2 == 0:
            try:
                from services.hh_monitor import check_vacancies, format_vacancies

                vacancies = await check_vacancies()
                if vacancies:
                    parts.append("\n" + format_vacancies(vacancies))
                else:
                    parts.append("\n\U0001f50d Вакансии AI Security: новых нет")
            except Exception as exc:
                logger.error("BRIEF | hh check failed: %s", exc)

        text = "\n".join(parts)
        if len(text) > 4000:
            text = text[:3990] + "…"
        await _safe_send(config.admin_id, text)
        logger.info("BRIEF | Morning brief sent (%d chars)", len(text))


async def _safe_send(chat_id: int, text: str, markup=None) -> None:
    if _bot is None:
        return
    try:
        await _bot.send_message(chat_id, text, reply_markup=markup)
    except Exception:
        pass
