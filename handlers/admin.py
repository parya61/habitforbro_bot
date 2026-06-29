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
        f"\U0001f381 Настройка приза на <b>{month}</b>.\n"
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
        'или напиши «нет», если код будет позже:'
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
    code_line = (
        f"\nКод: <tg-spoiler>{code}</tg-spoiler>" if code else "\nКод: будет добавлен позже"
    )
    await message.answer(
        f"✅ Приз на {month} установлен!\n\n"
        f"\U0001f381 {desc}{code_line}"
    )


@router.message(Command("setgroup"))
async def cmd_setgroup(message: Message) -> None:
    """Привязывает текущий чат как группу для объявлений."""
    if message.from_user.id != config.admin_id:
        return
    chat_id = message.chat.id
    if chat_id > 0:
        await message.answer("Эту команду нужно использовать в группе, а не в ЛС.")
        return

    import os

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("GROUP_CHAT_ID="):
                lines[i] = "GROUP_CHAT_ID=" + str(chat_id) + "\n"
                found = True
                break
        if not found:
            lines.append("GROUP_CHAT_ID=" + str(chat_id) + "\n")
        with open(env_path, "w") as f:
            f.writelines(lines)
    except Exception:
        pass

    config.group_chat_id = chat_id
    await message.answer(
        "✅ Группа привязана!\n"
        "Chat ID: <code>" + str(chat_id) + "</code>\n\n"
        "Теперь итоги месяца и призы будут публиковаться здесь."
    )


@router.message(Command("announce_results"))
async def cmd_announce_results(message: Message) -> None:
    """Ручной запуск объявления итогов месяца (для тестирования)."""
    if message.from_user.id != config.admin_id:
        return
    from services.scheduler import _check_month_end

    await message.answer("Запускаю объявление итогов...")
    await _check_month_end()


@router.message(Command("announce_prize"))
async def cmd_announce_prize(message: Message) -> None:
    """Ручной запуск объявления приза нового месяца."""
    if message.from_user.id != config.admin_id:
        return
    from services.scheduler import _month_start_announce

    await message.answer("Объявляю приз месяца...")
    await _month_start_announce()
