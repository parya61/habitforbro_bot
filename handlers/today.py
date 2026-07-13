"""Раздел «Сегодня»: отметка привычек галочками и количеством."""
from __future__ import annotations

import random
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import get_habit, get_log, list_habits, upsert_log
from services.achievements import check_after_log
from services.streaks import current_streak, habit_freeze_usage, is_scheduled
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



async def show_today(message: Message, session: AsyncSession, user: User) -> None:
    today = user_today(user)

    all_habits = await list_habits(session, user.id)
    kb = InlineKeyboardBuilder()
    text_parts = []

    # Секция «Вчера» — неотмеченные привычки за вчера
    yesterday = today - timedelta(days=1)
    y_unmarked = []
    for h in all_habits:
        if is_scheduled(h, yesterday):
            log = await get_log(session, h.id, yesterday)
            if not log or not log.done:
                y_unmarked.append(h)
    if y_unmarked:
        text_parts.append("📅 <b>Вчера</b> (не отмечено):")
        for h in y_unmarked:
            kb.button(
                text=f"📅 {h.emoji} {h.title}",
                callback_data=f"tgy:{h.id}",
            )

    # Секция «Сегодня»
    today_habits = [h for h in all_habits if is_scheduled(h, today)]
    if today_habits:
        text_parts.append("\n📋 <b>Сегодня</b>")
        for h in today_habits:
            log = await get_log(session, h.id, today)
            done = log is not None and log.done
            mark = "✅" if done else "⬜"
            extra = ""
            if h.type == "quantitative" and log and log.amount:
                extra = f" ({log.amount}/{h.target})"
            kb.button(
                text=f"{mark} {h.emoji} {h.title}{extra}",
                callback_data=f"tg:{h.id}",
            )

    # Уведомление о заморозках
    yesterday = today - timedelta(days=1)
    freeze_names = []
    for h in all_habits:
        if is_scheduled(h, yesterday):
            log = await get_log(session, h.id, yesterday)
            if not log or not log.done:
                used, total = await habit_freeze_usage(session, h, today)
                if 0 < used <= total:
                    freeze_names.append(f"{h.emoji} {h.title}")
    if freeze_names:
        names = ", ".join(freeze_names)
        text_parts.append(f"\n❄️ Вчера сработала заморозка: {names}")

    if not today_habits and not text_parts:
        await message.answer(
            "На сегодня привычек нет. Добавь их в разделе «➕ Привычки»."
        )
        return

    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="go:today"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"),
    )
    await message.answer(
        "\n".join(text_parts) if text_parts else "📋 <b>Сегодня</b>\nНажми на привычку, чтобы отметить:",
        reply_markup=kb.as_markup(),
    )


@router.message(Command("today"))
@router.message(F.text == "📋 Сегодня")
async def cmd_today(message: Message, session: AsyncSession, user: User) -> None:
    await show_today(message, session, user)


@router.callback_query(F.data.startswith("tgy:"))
async def toggle_yesterday(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    habit_id = int(callback.data.split(":")[1])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Не найдено", show_alert=True)
        return
    yesterday = user_today(user) - timedelta(days=1)
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
    await _refresh_and_reply(callback, session, user, habit, user_today(user), new_done)


@router.callback_query(F.data.startswith("tg:"))
async def toggle_habit(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    habit_id = int(callback.data.split(":")[1])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Не найдено", show_alert=True)
        return

    today = user_today(user)

    log = await get_log(session, habit_id, today)
    already_done = log is not None and log.done

    if habit.type == "quantitative" and not already_done:
        await state.set_state(LogQuantity.amount)
        await state.update_data(habit_id=habit_id, log_date=today.isoformat())
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🎯 Цель ({habit.target})", callback_data=f"amt:{habit.target}")
        kb.button(text="➕ Больше", callback_data="amt:more")
        kb.button(text="➖ Меньше", callback_data="amt:less")
        kb.adjust(1)
        await callback.message.answer(
            f"Сколько {esc(habit.unit) or 'раз'}? Введи число или выбери:",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    new_done = not already_done
    await upsert_log(session, habit_id, today, done=new_done)
    await _refresh_and_reply(callback, session, user, habit, today, new_done)


async def _refresh_and_reply(callback, session, user, habit, today, new_done):
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


@router.callback_query(F.data.startswith("amt:"), LogQuantity.amount)
async def quick_amount(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    habit = await get_habit(session, data.get("habit_id"))
    if not habit:
        await state.clear()
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    choice = callback.data.split(":")[1]
    log_date = date.fromisoformat(data["log_date"]) if "log_date" in data else user_today(user)

    if choice == "more":
        await callback.message.answer("Введи число (больше цели):")
        return
    if choice == "less":
        await callback.message.answer("Введи число (меньше цели):")
        return

    amount = int(choice)
    await state.clear()
    await upsert_log(session, habit.id, log_date, done=True, amount=amount)
    await _refresh_and_reply(callback, session, user, habit, user_today(user), True)


@router.message(LogQuantity.amount)
async def enter_amount(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = await get_habit(session, data.get("habit_id"))
    if not habit:
        await state.clear()
        await message.answer("Привычка не найдена.")
        return
    log_date = date.fromisoformat(data["log_date"]) if "log_date" in data else user_today(user)
    await state.clear()
    await upsert_log(session, habit.id, log_date, done=True, amount=int(raw))

    today = user_today(user)
    streak = await current_streak(session, habit, today)
    msg = f"Записал {raw} {esc(habit.unit) or ''}! 🔥 Серия: {streak} дн.".strip()
    badges = await check_after_log(session, user.id, habit, today)
    if badges:
        msg += "\n\n🏅 Новое достижение:\n" + "\n".join(badges)
    await message.answer(msg)
