"""Middleware: открывает сессию БД и подгружает пользователя.

Бот открытый. Любой пользователь получает доступ автоматически.
Единственное требование — /start для создания записи в БД.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from db.database import get_session
from db.queries import get_user_by_tg


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

            if user is not None:
                if not user.has_access:
                    user.has_access = True
                    await session.commit()
                return await handler(event, data)

            if isinstance(event, Message):
                text = (event.text or "").strip()
                if text == "/start":
                    return await handler(event, data)
                await event.answer(
                    "Нажми /start, чтобы начать."
                )
                return None

            if isinstance(event, CallbackQuery):
                await event.answer("Нажми /start, чтобы начать", show_alert=True)
                return None

            return None
