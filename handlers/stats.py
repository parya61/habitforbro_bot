"""Личная статистика, серии и достижения пользователя."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import list_achievements, list_habits
from keyboards.nav import home_kb
from services.achievements import ACHIEVEMENTS
from services.stats import user_stats
from services.streaks import best_streak, current_streak, habit_freeze_usage
from utils import esc

router = Router()


@router.message(Command("stats"))
@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message, session: AsyncSession, user: User) -> None:
    stats = await user_stats(session, user.id)
    lines = [
        "📊 <b>Твоя статистика</b>\n",
        f"Активных привычек: {stats.active_habits}",
        f"За неделю: {stats.week_done}/{stats.week_planned} ({stats.week_percent}%)",
        f"За месяц: {stats.month_done}/{stats.month_planned} ({stats.month_percent}%)",
        f"Всего отметок за месяц: {stats.total_marks}",
        f"🏆 Рекорд серии: {stats.record_streak} дн.",
        "",
        "<b>Серии по привычкам:</b>",
    ]
    habits = await list_habits(session, user.id)
    if not habits:
        lines.append("— пока нет привычек")
    for h in habits:
        cur = await current_streak(session, h, None)
        best = await best_streak(session, h, None)
        used, total = await habit_freeze_usage(session, h)
        tag = " 🔒" if h.is_private else ""
        freeze_str = f" | ❄️ {used}/{total}" if used > 0 else ""
        lines.append(f"{h.emoji} {esc(h.title)}{tag}: 🔥 {cur} | 🏆 {best}{freeze_str}")

    # Достижения.
    achs = await list_achievements(session, user.id)
    if achs:
        lines.append("\n<b>🏅 Достижения:</b>")
        seen = set()
        for a in achs:
            if a.code in seen:
                continue
            seen.add(a.code)
            lines.append(ACHIEVEMENTS.get(a.code, a.code))

    await message.answer("\n".join(lines), reply_markup=home_kb())
