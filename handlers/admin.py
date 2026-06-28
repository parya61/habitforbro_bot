"""Админ-команды: управление призами."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.queries import set_prize
from states import AdminPrize

router = Router()


def _next_month() -> str:
    today = date.today()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next.strftime("%Y-%m")


@router.message(Command("setprize"))
async def cmd_setprize(message: Message, state: FSMContext) -> None:
    if message.from_user.id != config.admin_id:
        return
    month = _next_month()
    await state.set_state(AdminPrize.description)
    await state.update_data(prize_month=month)
    await message.answer(
        f"🎁 Настройка приза на <b>{month}</b>.\n"
        "Опиши приз (например: подписка Яндекс Музыка на 1 месяц):"
    )


@router.message(AdminPrize.description)
async def prize_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Описание не может быть пустым:")
        return
    await state.update_data(prize_desc=text)
    await state.set_state(AdminPrize.code)
    await message.answer(
        "Теперь введи код/ссылку приза (промокод, ссылка на подарок) "
        "или напиши «нет», если код будет позже:"
    )


@router.message(AdminPrize.code)
async def prize_code(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    no_code = raw.lower() in {"нет", "no", "-", "позже"}
    data = await state.get_data()
    await state.clear()

    month = data.get("prize_month", _next_month())
    desc = data.get("prize_desc", "Приз")
    code = None if no_code else raw

    await set_prize(session, month, desc, code)
    code_line = f"\nКод: <tg-spoiler>{code}</tg-spoiler>" if code else "\nКод: будет добавлен позже"
    await message.answer(
        f"✅ Приз на {month} установлен!\n\n"
        f"🎁 {desc}{code_line}"
    )
