"""Участники: список, публичные привычки и серии, реакции-поддержка.

Приватные привычки (скрытые ото всех) и приватный дневник здесь не показываются.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import get_user_by_tg, list_public_habits, list_users
from services.streaks import best_streak, current_streak
from states import SendMessage
from utils import display_name, esc

router = Router()

REACTIONS = ["🔥", "👏", "💪"]


PAGE_SIZE = 10


async def show_members(message: Message, session: AsyncSession, page: int = 0) -> None:
    users = await list_users(session)
    if not users:
        await message.answer("Участников пока нет.")
        return
    total_pages = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    kb = InlineKeyboardBuilder()
    for u in page_users:
        kb.button(text=f"👤 {display_name(u)}", callback_data=f"usr:{u.telegram_id}")
    kb.adjust(1)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"members:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"members:{page + 1}"))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"))
    await message.answer("👥 <b>Участники</b>", reply_markup=kb.as_markup())


@router.message(Command("members"))
@router.message(F.text == "👥 Участники")
async def cmd_members(message: Message, session: AsyncSession) -> None:
    await show_members(message, session)


@router.callback_query(F.data.startswith("members:"))
async def paginate_members(callback: CallbackQuery, session: AsyncSession) -> None:
    page = int(callback.data.split(":")[1])
    await show_members(callback.message, session, page)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("usr:"))
async def show_member(callback: CallbackQuery, session: AsyncSession) -> None:
    target_tg = int(callback.data.split(":")[1])
    target = await get_user_by_tg(session, target_tg)
    if not target:
        await callback.answer("Участник не найден", show_alert=True)
        return

    name = display_name(target)
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
    kb.button(text="💬 Написать", callback_data=f"msg:{target_tg}")
    kb.adjust(3, 1)
    kb.row(
        InlineKeyboardButton(text="⬅️ Участники", callback_data="go:members"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"),
    )
    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("react:"))
async def send_reaction(callback: CallbackQuery, user: User) -> None:
    _, target_tg, reaction = callback.data.split(":")
    sender = display_name(user)
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"msg:{user.telegram_id}")
    try:
        await callback.bot.send_message(
            int(target_tg),
            f"{reaction} <b>{esc(sender)}</b> поддерживает тебя!",
            reply_markup=kb.as_markup(),
        )
        await callback.answer(f"Отправлено {reaction}")
    except Exception:
        await callback.answer("Не удалось отправить реакцию", show_alert=True)


@router.callback_query(F.data.startswith("msg:"))
async def start_send_message(
    callback: CallbackQuery, state: FSMContext
) -> None:
    target_tg = int(callback.data.split(":")[1])
    await state.set_state(SendMessage.text)
    await state.update_data(msg_target=target_tg)
    await callback.message.answer("✍️ Напиши сообщение (до 500 символов):")
    await callback.answer()


@router.message(SendMessage.text)
async def finish_send_message(
    message: Message, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    target_tg = data.get("msg_target")
    await state.clear()
    text = (message.text or "").strip()[:500]
    if not text:
        await message.answer("Пустое сообщение не отправлю.")
        return
    sender = display_name(user)
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"msg:{user.telegram_id}")
    try:
        await message.bot.send_message(
            target_tg,
            f"💬 <b>Сообщение от {esc(sender)}:</b>\n\n{esc(text)}",
            reply_markup=kb.as_markup(),
        )
        await message.answer("✅ Сообщение отправлено!")
    except Exception:
        await message.answer("Не удалось отправить сообщение.")
