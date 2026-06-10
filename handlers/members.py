"""Участники: список, публичные привычки и серии, реакции-поддержка.

Приватные привычки (скрытые ото всех) и приватный дневник здесь не показываются.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import get_user_by_tg, list_public_habits, list_users
from services.streaks import best_streak, current_streak
from utils import esc

router = Router()

REACTIONS = ["🔥", "👏", "💪"]


async def show_members(message: Message, session: AsyncSession) -> None:
    users = await list_users(session)
    if not users:
        await message.answer("Участников пока нет.")
        return
    kb = InlineKeyboardBuilder()
    for u in users:
        name = u.name or u.username or f"id{u.telegram_id}"
        kb.button(text=f"👤 {name}", callback_data=f"usr:{u.telegram_id}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"))
    await message.answer("👥 <b>Участники</b>", reply_markup=kb.as_markup())


@router.message(Command("members"))
@router.message(F.text == "👥 Участники")
async def cmd_members(message: Message, session: AsyncSession) -> None:
    await show_members(message, session)


@router.callback_query(F.data.startswith("usr:"))
async def show_member(callback: CallbackQuery, session: AsyncSession) -> None:
    target_tg = int(callback.data.split(":")[1])
    target = await get_user_by_tg(session, target_tg)
    if not target:
        await callback.answer("Участник не найден", show_alert=True)
        return

    name = target.name or target.username or f"id{target.telegram_id}"
    habits = await list_public_habits(session, target.id)

    lines = [f"👤 <b>{esc(name)}</b>\n"]
    if not habits:
        lines.append("Нет публичных привычек.")
    else:
        lines.append("<b>Публичные привычки:</b>")
        for h in habits:
            cur = await current_streak(session, h, None)
            best = await best_streak(session, h, None)
            lines.append(f"{h.emoji} {esc(h.title)}: 🔥 {cur} | 🏆 {best}")

    kb = InlineKeyboardBuilder()
    for r in REACTIONS:
        kb.button(text=r, callback_data=f"react:{target_tg}:{r}")
    kb.adjust(3)
    kb.row(
        InlineKeyboardButton(text="⬅️ Участники", callback_data="go:members"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"),
    )
    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("react:"))
async def send_reaction(callback: CallbackQuery, user: User) -> None:
    _, target_tg, reaction = callback.data.split(":")
    sender = user.name or user.username or "Кто-то"
    try:
        await callback.bot.send_message(
            int(target_tg), f"{reaction} {esc(sender)} поддерживает тебя!"
        )
        await callback.answer(f"Отправлено {reaction}")
    except Exception:
        await callback.answer("Не удалось отправить реакцию", show_alert=True)
