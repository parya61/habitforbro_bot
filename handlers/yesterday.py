"""Раздел «Вчера»: отметка привычек, которые забыл вчера (до 12:00)."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from db.models import User
from db.queries import get_habit, get_log, list_habits, upsert_log
from services.achievements import check_after_log
from services.streaks import current_streak, is_scheduled
from states import LogQuantity
from utils import esc, user_today

router = Router()

MOTIVATION = [
    "Отлично! Так держать! 💪",
    "Ещё один шаг к цели! 🚀",
    "Ты молодец! 🌟",
    "Прогресс налицо! 🔥",
    "Гордимся тобой! 👏",
]

DEADLINE_HOUR = 12


def _user_now(user: User) -> datetime:
    tz = ZoneInfo(user.timezone)
    return datetime.now(tz)


async def show_yesterday(message: Message, session: AsyncSession, user: User) -> None:
    now = _user_now(user)
    if now.hour >= DEADLINE_HOUR:
        await message.answer(
            "⏰ Отметить привычки за вчера можно только до 12:00.\n"
            "Сейчас уже поздно — завтра не забудь!",
        )
        return

    today = now.date()
    yesterday = today - timedelta(days=1)

    all_habits = await list_habits(session, user.id)
    kb = InlineKeyboardBuilder()
    unmarked = []
    for h in all_habits:
        if is_scheduled(h, yesterday):
            log = await get_log(session, h.id, yesterday)
            if not log or not log.done:
                unmarked.append(h)

    if not unmarked:
        await message.answer("✅ За вчера всё отмечено, молодец!")
        return

    text = f"📅 <b>Вчера</b> ({yesterday.strftime('%d.%m')})\nНе отмечено — нажми, чтобы отметить:"
    for h in unmarked:
        kb.button(
            text=f"📅 {h.emoji} {h.title}",
            callback_data=f"tgy:{h.id}",
        )
    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="go:yesterday"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"),
    )
    await message.answer(text, reply_markup=kb.as_markup())


@router.message(Command("yesterday"))
@router.message(F.text == "📅 Вчера")
async def cmd_yesterday(message: Message, session: AsyncSession, user: User) -> None:
    await show_yesterday(message, session, user)


@router.callback_query(F.data.startswith("tgy:"))
async def toggle_yesterday(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    now = _user_now(user)
    if now.hour >= DEADLINE_HOUR:
        await callback.answer("Уже после 12:00, нельзя отметить за вчера", show_alert=True)
        return

    habit_id = int(callback.data.split(":")[1])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Не найдено", show_alert=True)
        return
    yesterday = now.date() - timedelta(days=1)
    log = await get_log(session, habit_id, yesterday)
    already_done = log is not None and log.done

    if habit.type == "quantitative" and not already_done:
        await state.set_state(LogQuantity.amount)
        await state.update_data(habit_id=habit_id, log_date=yesterday.isoformat())
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🎯 Цель ({habit.target})", callback_data=f"amt:{habit.target}")
        kb.button(text="➕ Больше", callback_data="amt:more")
        kb.button(text="➖ Меньше", callback_data="amt:less")
        kb.adjust(1)
        await callback.message.answer(
            f"📅 Вчера: сколько {esc(habit.unit) or 'раз'}?",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    new_done = not already_done
    await upsert_log(session, habit_id, yesterday, done=new_done)
    today = now.date()
    if new_done:
        streak = await current_streak(session, habit, today)
        msg = f"{random.choice(MOTIVATION)}\n🔥 Серия: {streak} дн."
        badges = await check_after_log(session, user.id, habit, today)
        if badges:
            msg += "\n\n🏅 Новое достижение:\n" + "\n".join(badges)
        await callback.answer()
        await callback.message.answer(msg)
    else:
        await callback.answer("Отметка снята")
