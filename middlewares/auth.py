"""Middleware: открывает сессию БД, подгружает пользователя и контролирует доступ.

Бот закрытый. Пока пользователь не получил доступ (кодовое слово или whitelist),
ему доступен только сценарий /start и ввод кодового слова.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from db.database import get_session
from db.queries import get_user_by_tg
from states import Registration


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with get_session() as session:
            data["session"] = session

            tg_user = data.get("event_from_user")
            user = None
            if tg_user is not None:
                user = await get_user_by_tg(session, tg_user.id)
            data["user"] = user

            if user is not None and user.has_access:
                return await handler(event, data)

            # Нет доступа — пропускаем только /start и ввод кодового слова.
            state: FSMContext | None = data.get("state")
            current = await state.get_state() if state else None

            if isinstance(event, Message):
                text = (event.text or "").strip()
                if text == "/start" or current == Registration.code.state:
                    return await handler(event, data)
                await event.answer(
                    "🔒 Доступ закрыт. Нажмите /start, чтобы войти."
                )
                return None

            if isinstance(event, CallbackQuery):
                await event.answer("🔒 Сначала войдите через /start", show_alert=True)
                return None

            return None
