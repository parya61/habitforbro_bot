"""Настройки: часовой пояс, рассылки, приватность дневника."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import update_user_settings
from states import SettingsFlow
from utils import display_name

router = Router()


def _settings_kb(user: User) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    morning = "вкл ✅" if user.morning_enabled else "выкл ⬜"
    evening = "вкл ✅" if user.evening_enabled else "выкл ⬜"
    diary = "приватный 🔒" if user.diary_private else "публичный 👥"
    kb.button(text=f"🌅 Утренние сообщения: {morning}", callback_data="set:morning")
    kb.button(text=f"🌙 Вечерние напоминания: {evening}", callback_data="set:evening")
    kb.button(text=f"📔 Дневник: {diary}", callback_data="set:diary")
    nick_label = display_name(user)
    kb.button(text=f"✏️ Никнейм: {nick_label}", callback_data="set:nickname")
    kb.button(text=f"🌍 Часовой пояс: {user.timezone}", callback_data="set:tz")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"))
    return kb


def _settings_text(user: User) -> str:
    return (
        "⚙️ <b>Настройки</b>\n\n"
        "Дневник по умолчанию приватный. Привычки делаются публичными или "
        "скрытыми ото всех при создании (и меняются в карточке привычки)."
    )


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message, user: User) -> None:
    await message.answer(_settings_text(user), reply_markup=_settings_kb(user).as_markup())


@router.callback_query(F.data == "set:morning")
async def toggle_morning(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await update_user_settings(session, user, morning_enabled=not user.morning_enabled)
    await callback.message.edit_reply_markup(reply_markup=_settings_kb(user).as_markup())
    await callback.answer()


@router.callback_query(F.data == "set:evening")
async def toggle_evening(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await update_user_settings(session, user, evening_enabled=not user.evening_enabled)
    await callback.message.edit_reply_markup(reply_markup=_settings_kb(user).as_markup())
    await callback.answer()


@router.callback_query(F.data == "set:diary")
async def toggle_diary(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await update_user_settings(session, user, diary_private=not user.diary_private)
    await callback.message.edit_reply_markup(reply_markup=_settings_kb(user).as_markup())
    await callback.answer("Изменено")


@router.callback_query(F.data == "set:nickname")
async def set_nickname(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.nickname)
    await callback.message.answer(
        "Введи новый никнейм (до 64 символов) или «сброс», чтобы вернуть имя из Telegram:"
    )
    await callback.answer()


@router.message(SettingsFlow.nickname)
async def enter_nickname(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    raw = (message.text or "").strip()
    reset = raw.lower() in {"сброс", "сбросить", "reset", "-"}
    if not reset and not raw:
        await message.answer("Никнейм не может быть пустым. Попробуй ещё:")
        return
    nickname = None if reset else raw[:64]
    await update_user_settings(session, user, nickname=nickname)
    await state.clear()
    label = "сброшен на имя из Telegram" if reset else f"установлен: {raw[:64]}"
    await message.answer(f"✅ Никнейм {label}")


@router.callback_query(F.data == "set:tz")
async def set_tz(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.timezone)
    await callback.message.answer(
        "Введи часовой пояс (например, Europe/Moscow, Asia/Yekaterinburg):"
    )
    await callback.answer()


@router.message(SettingsFlow.timezone)
async def enter_tz(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    tz = (message.text or "").strip()
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        await message.answer("Не знаю такой пояс. Пример: Europe/Moscow. Попробуй ещё:")
        return
    await update_user_settings(session, user, timezone=tz)
    await state.clear()
    await message.answer(f"✅ Часовой пояс: {tz}")
