"""Фоллбэк: мягко реагируем на непонятный ввод вне сценариев.

Регистрируется ПОСЛЕДНИМ — срабатывает, только если ни один другой обработчик
(включая шаги мастеров) не подошёл."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from keyboards.nav import main_inline_kb

router = Router()


@router.message()
async def unknown(message: Message) -> None:
    await message.answer(
        "Не совсем понял 🤔\nВоспользуйся кнопками меню ниже или нажми /start.",
        reply_markup=main_inline_kb(),
    )
