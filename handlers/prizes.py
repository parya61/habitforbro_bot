"""Раздел «Призы»: текущий приз, лидер месяца, история победителей."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    get_prize,
    get_user_by_tg,
    list_prizes,
    list_public_habits,
    list_users,
)
from keyboards.nav import home_kb
from services.streaks import completion_rate
from utils import display_name, esc

router = Router()


async def _current_leader(session: AsyncSession, month_start: date, month_end: date):
    best_user = None
    best_rate = -1.0
    for user in await list_users(session):
        habits = await list_public_habits(session, user.id)
        if not habits:
            continue
        total_done = total_planned = 0
        for h in habits:
            d, p = await completion_rate(session, h, month_start, month_end)
            total_done += d
            total_planned += p
        rate = total_done / total_planned if total_planned > 0 else 0
        if rate > best_rate:
            best_rate = rate
            best_user = user
    return best_user, best_rate


async def show_prizes(message: Message, session: AsyncSession, user: User) -> None:
    today = date.today()
    current_month = today.strftime("%Y-%m")
    month_start = today.replace(day=1)

    lines = ["🎁 <b>Призы</b>\n"]

    # Текущий месяц
    prize = await get_prize(session, current_month)
    if prize:
        lines.append(f"<b>Приз месяца ({current_month}):</b>")
        lines.append(f"🎁 {esc(prize.description)}")
        if prize.winner_user_id:
            lines.append(f"🏆 Победитель: {display_name(prize.winner)}")
            if prize.winner_user_id == user.id and prize.prize_code:
                lines.append(f"🔑 Твой код: <tg-spoiler>{esc(prize.prize_code)}</tg-spoiler>")
        else:
            leader, rate = await _current_leader(session, month_start, today)
            if leader:
                lines.append(
                    f"📊 Лидер сейчас: {esc(display_name(leader))} ({round(rate * 100)}%)"
                )
    else:
        lines.append("В этом месяце приз пока не установлен.")

    # История
    all_prizes = await list_prizes(session, limit=6)
    past = [p for p in all_prizes if p.month != current_month and p.winner_user_id]
    if past:
        lines.append("\n<b>История:</b>")
        for p in past[:5]:
            winner_name = display_name(p.winner) if p.winner else "—"
            lines.append(f"{p.month}: {esc(p.description)} → {esc(winner_name)}")

    await message.answer("\n".join(lines), reply_markup=home_kb())


@router.message(Command("prizes"))
@router.message(F.text == "🎁 Призы")
async def cmd_prizes(message: Message, session: AsyncSession, user: User) -> None:
    await show_prizes(message, session, user)
