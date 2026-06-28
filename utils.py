"""Вспомогательные функции: безопасный HTML и устойчивое редактирование сообщений."""
from __future__ import annotations

import html
from datetime import date, datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


def esc(text: object) -> str:
    """Экранирует текст пользователя для безопасной вставки в HTML-сообщение.

    Без этого символы < > & в названии привычки, заметке или имени ломают
    разметку и отправка падает.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def display_name(user) -> str:
    return user.nickname or user.name or user.username or f"id{user.telegram_id}"


def user_today(user) -> date:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(user.timezone)
    return datetime.now(tz).date()


def user_now(user) -> datetime:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(user.timezone)
    return datetime.now(tz)


async def safe_edit_text(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Редактирует текст сообщения, не падая на типовых ошибках Telegram.

    Игнорирует «message is not modified»; если сообщение нельзя отредактировать
    (слишком старое/удалено) — отправляет новое.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        try:
            await message.answer(text, reply_markup=reply_markup)
        except TelegramBadRequest:
            pass


async def safe_edit_markup(
    message: Message, reply_markup: InlineKeyboardMarkup | None
) -> None:
    """Обновляет только клавиатуру, игнорируя «not modified» и устаревшие сообщения."""
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest:
        pass
