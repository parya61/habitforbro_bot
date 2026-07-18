"""AI-аналитика: персональный разбор привычек, дисциплины и прогресса."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AnalyticsSession, User
from keyboards.nav import home_kb
from services.ai_analytics import (
    SYSTEM_PROMPT,
    ask_deepseek,
    build_user_context,
)
from states import AnalyticsFlow

router = Router()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MAX_MESSAGES = 5
COOLDOWN_DAYS = 7


async def _get_active_session(
    session: AsyncSession, user_id: int
) -> AnalyticsSession | None:
    """Находит активную (не исчерпанную) сессию за текущую неделю."""
    week_ago = datetime.utcnow() - timedelta(days=COOLDOWN_DAYS)
    res = await session.execute(
        select(AnalyticsSession)
        .where(
            AnalyticsSession.user_id == user_id,
            AnalyticsSession.started_at >= week_ago,
        )
        .order_by(AnalyticsSession.started_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _can_start_session(
    session: AsyncSession, user_id: int
) -> tuple[bool, str]:
    """Проверяет, может ли пользователь начать новую сессию."""
    existing = await _get_active_session(session, user_id)
    if existing is None:
        return True, ""
    if existing.messages_used < existing.max_messages:
        return True, ""
    remaining = existing.started_at + timedelta(days=COOLDOWN_DAYS) - datetime.utcnow()
    days = max(1, remaining.days)
    return False, f"Следующая сессия будет доступна через {days} дн."


def _analytics_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Начать анализ", callback_data="analytics:start")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(1)
    return kb


def _chat_kb(messages_left: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"💬 Вопросов осталось: {messages_left}",
        callback_data="analytics:info",
    )
    kb.button(text="🏠 Завершить", callback_data="analytics:end")
    kb.adjust(1)
    return kb


@router.callback_query(F.data == "analytics:weekly_start")
async def weekly_analytics_start(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    """Start a follow-up chat session from the weekly Kerya analysis."""
    if not DEEPSEEK_API_KEY:
        await callback.answer("AI-аналитика недоступна", show_alert=True)
        return

    analytics_session = AnalyticsSession(
        user_id=user.id, max_messages=3
    )
    session.add(analytics_session)
    await session.commit()
    await session.refresh(analytics_session)

    await callback.answer()

    wait_msg = await callback.message.answer("⏳ Собираю контекст...")

    context = await build_user_context(session, user)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Данные пользователя:\n\n{context}"},
        {"role": "assistant", "content": "Я изучил твои данные. Задавай вопросы!"},
    ]

    await state.set_state(AnalyticsFlow.chat)
    await state.update_data(
        session_id=analytics_session.id,
        history=messages,
    )

    await wait_msg.edit_text(
        "🧠 Керя готов ответить на вопросы по твоей неделе.\n"
        "Напиши что интересует — 3 вопроса доступно.",
        reply_markup=_chat_kb(3).as_markup(),
    )


@router.callback_query(F.data == "analytics:start")
async def start_analytics(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    if not DEEPSEEK_API_KEY:
        await callback.answer("AI-аналитика недоступна", show_alert=True)
        return

    can, reason = await _can_start_session(session, user.id)
    existing = await _get_active_session(session, user.id)

    if existing and existing.messages_used < existing.max_messages:
        analytics_session = existing
    elif can:
        analytics_session = AnalyticsSession(
            user_id=user.id, max_messages=MAX_MESSAGES
        )
        session.add(analytics_session)
        await session.commit()
        await session.refresh(analytics_session)
    else:
        await callback.answer(reason, show_alert=True)
        return

    await callback.answer()

    wait_msg = await callback.message.answer("⏳ Анализирую твои данные...")

    context = await build_user_context(session, user)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Вот данные пользователя:\n\n{context}\n\n"
                "Проанализируй: что получается, где провалы, "
                "какие закономерности видишь. Дай 2-3 конкретных совета."
            ),
        },
    ]

    resp = await ask_deepseek(DEEPSEEK_API_KEY, messages)

    analytics_session.messages_used += 1
    await session.commit()

    if not resp.ok:
        await wait_msg.edit_text(
            "⚠️ Не удалось получить анализ. Попробуй позже.",
            reply_markup=home_kb(),
        )
        return

    left = analytics_session.max_messages - analytics_session.messages_used

    await state.set_state(AnalyticsFlow.chat)
    await state.update_data(
        session_id=analytics_session.id,
        history=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Данные пользователя:\n\n{context}"},
            {"role": "assistant", "content": resp.text},
        ],
    )

    await wait_msg.edit_text(
        f"🧠 <b>Анализ от Кери</b>\n\n{resp.text}",
        reply_markup=_chat_kb(left).as_markup(),
    )


@router.message(AnalyticsFlow.chat)
async def analytics_chat(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    session_id = data.get("session_id")
    history = data.get("history", [])

    if not session_id:
        await state.clear()
        await message.answer("Сессия не найдена. Начни заново.", reply_markup=home_kb())
        return

    res = await session.execute(
        select(AnalyticsSession).where(AnalyticsSession.id == session_id)
    )
    analytics_session = res.scalar_one_or_none()
    if not analytics_session or analytics_session.messages_used >= analytics_session.max_messages:
        await state.clear()
        await message.answer(
            "Лимит сообщений исчерпан. Новая сессия — через неделю.",
            reply_markup=home_kb(),
        )
        return

    history.append({"role": "user", "content": message.text})

    wait_msg = await message.answer("⏳ Думаю...")

    resp = await ask_deepseek(DEEPSEEK_API_KEY, history)

    analytics_session.messages_used += 1
    await session.commit()

    if not resp.ok:
        await wait_msg.edit_text("⚠️ Ошибка. Попробуй ещё раз.")
        return

    history.append({"role": "assistant", "content": resp.text})
    left = analytics_session.max_messages - analytics_session.messages_used

    await state.update_data(history=history)

    if left <= 0:
        await state.clear()
        await wait_msg.edit_text(
            f"🧠 {resp.text}\n\n"
            "—\n"
            "Сессия завершена. Новая будет доступна через неделю.",
            reply_markup=home_kb(),
        )
    else:
        await wait_msg.edit_text(
            f"🧠 {resp.text}",
            reply_markup=_chat_kb(left).as_markup(),
        )


@router.callback_query(F.data == "analytics:info")
async def analytics_info(callback: CallbackQuery) -> None:
    await callback.answer(
        "Напиши вопрос в чат — Керя ответит на основе твоих данных.",
        show_alert=True,
    )


@router.callback_query(F.data == "analytics:end")
async def analytics_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    from utils import safe_edit_text
    await safe_edit_text(
        callback.message,
        "🧠 Сессия аналитики завершена. Возвращайся, когда будет нужно.",
        reply_markup=home_kb(),
    )
