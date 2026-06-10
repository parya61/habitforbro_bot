"""Дневник: запись за день, подсказки, настроение, приватность, просмотр истории."""
from __future__ import annotations

import random
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import add_diary_entry, list_diary_entries
from keyboards.nav import home_kb
from states import DiaryFlow
from utils import esc

router = Router()

PROMPTS = [
    "Что сегодня порадовало?",
    "За что ты благодарен?",
    "Что хочешь улучшить завтра?",
    "Какой момент дня запомнился больше всего?",
    "Что нового ты узнал сегодня?",
    "Чем ты гордишься сегодня?",
]

MOODS = ["😀", "🙂", "😐", "😔", "😢", "😤", "😴"]


def _diary_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Написать запись", callback_data="diary:write")
    kb.button(text="💡 Подсказка дня", callback_data="diary:prompt")
    kb.button(text="📚 Прошлые записи", callback_data="diary:history")
    kb.adjust(1)
    return kb


@router.message(Command("diary"))
@router.message(F.text == "📔 Дневник")
async def cmd_diary(message: Message) -> None:
    await message.answer(
        "📔 <b>Дневник</b>\nЗаписи приватны — их видишь только ты.",
        reply_markup=_diary_menu_kb().as_markup(),
    )


@router.callback_query(F.data == "diary:prompt")
async def diary_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DiaryFlow.text)
    await callback.message.answer(
        f"💡 <i>{random.choice(PROMPTS)}</i>\n\nНапиши ответ — это станет записью дня."
    )
    await callback.answer()


@router.callback_query(F.data == "diary:write")
async def diary_write(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DiaryFlow.text)
    await callback.message.answer("✍️ Напиши запись за сегодня:")
    await callback.answer()


@router.message(DiaryFlow.text)
async def diary_save_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустую запись не сохраню. Напиши что-нибудь:")
        return
    await state.update_data(diary_text=text)
    # Предлагаем выбрать настроение (необязательно).
    kb = InlineKeyboardBuilder()
    for mood in MOODS:
        kb.button(text=mood, callback_data=f"mood:{mood}")
    kb.button(text="Без настроения", callback_data="mood:none")
    kb.adjust(4)
    await message.answer("Какое настроение?", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("mood:"), DiaryFlow.text)
async def diary_mood(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    mood = callback.data.split(":", 1)[1]
    mood = None if mood == "none" else mood
    data = await state.get_data()
    await state.clear()
    diary_text = data.get("diary_text")
    if not diary_text:
        await callback.answer("Запись устарела, начни заново", show_alert=True)
        return

    # Запись дневника по умолчанию приватная (видит только автор).
    await add_diary_entry(
        session,
        user_id=user.id,
        entry_date=date.today(),
        text=diary_text,
        mood=mood,
        private=user.diary_private,
    )
    tag = "🔒 приватно" if user.diary_private else "👥 видно участникам"
    await callback.message.edit_text(f"✅ Запись сохранена ({tag}).")
    await callback.message.answer("Что дальше?", reply_markup=home_kb())
    await callback.answer()


@router.callback_query(F.data == "diary:history")
async def diary_history(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    entries = await list_diary_entries(session, user.id, limit=10)
    if not entries:
        await callback.message.answer("Записей пока нет.")
        await callback.answer()
        return
    lines = ["📚 <b>Последние записи:</b>\n"]
    for e in entries:
        mood = f" {e.mood}" if e.mood else ""
        snippet = e.text if len(e.text) <= 200 else e.text[:200] + "…"
        lines.append(f"<b>{e.entry_date:%d.%m.%Y}</b>{mood}\n{esc(snippet)}\n")
    await callback.message.answer("\n".join(lines), reply_markup=home_kb())
    await callback.answer()
