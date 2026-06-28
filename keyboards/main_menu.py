"""Главное меню и общие клавиатуры."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Постоянная клавиатура внизу экрана — главное меню.
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Сегодня"), KeyboardButton(text="➕ Привычки")],
        [KeyboardButton(text="📔 Дневник"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="👥 Участники")],
        [KeyboardButton(text="🍵 Чай"), KeyboardButton(text="🎁 Призы")],
        [KeyboardButton(text="⚙️ Настройки")],
    ],
    resize_keyboard=True,
)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖️ Отмена", callback_data="cancel")]
        ]
    )
