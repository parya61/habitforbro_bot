"""Навигационные клавиатуры: inline-меню и кнопки возврата.

Цель — управлять ботом целиком кнопками, не вводя команды.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_inline_kb() -> InlineKeyboardMarkup:
    """Главное меню в виде inline-кнопок (дублирует нижнюю клавиатуру)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Сегодня", callback_data="go:today")
    kb.button(text="📅 Вчера", callback_data="go:yesterday")
    kb.button(text="➕ Привычки", callback_data="go:habits")
    kb.button(text="📔 Дневник", callback_data="go:diary")
    kb.button(text="📊 Статистика", callback_data="go:stats")
    kb.button(text="🏆 Рейтинг", callback_data="go:leaderboard")
    kb.button(text="👥 Участники", callback_data="go:members")
    kb.button(text="🎯 Цели", callback_data="go:goals")
    kb.button(text="🎁 Призы", callback_data="go:prizes")
    kb.button(text="💰 Финансы", callback_data="go:finance")
    kb.button(text="⚙️ Настройки", callback_data="go:settings")
    kb.button(text="ℹ️ Помощь", callback_data="go:help")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def home_kb() -> InlineKeyboardMarkup:
    """Одна кнопка «домой» — добавляется в конце сценариев."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="go:menu")
    return kb.as_markup()


def back_home_kb(back_cb: str, back_text: str = "⬅️ Назад") -> InlineKeyboardMarkup:
    """Кнопки «Назад» (в конкретный раздел) и «Меню»."""
    kb = InlineKeyboardBuilder()
    kb.button(text=back_text, callback_data=back_cb)
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb.as_markup()
