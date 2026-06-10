"""Рейтинг участников. Учитываются только публичные привычки —
скрытые ото всех в рейтинг не попадают."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.queries import list_public_habits, list_users
from services.streaks import best_streak, completion_rate
from utils import esc

router = Router()

PERIODS = {"week": ("неделю", 7), "month": ("месяц", 30)}
METRICS = {
    "percent": "по проценту выполнения",
    "streak": "по длине серии",
    "marks": "по числу отметок",
}


def _board_kb(period: str, metric: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for p, (label, _) in PERIODS.items():
        mark = "•" if p == period else ""
        kb.button(text=f"{mark}{label}", callback_data=f"lb:{p}:{metric}")
    for m, label in METRICS.items():
        mark = "•" if m == metric else ""
        kb.button(text=f"{mark}{label}", callback_data=f"lb:{period}:{m}")
    kb.adjust(2, 1, 1, 1)
    kb.row(InlineKeyboardButton(text="🏠 Меню", callback_data="go:menu"))
    return kb


async def _compute_board(
    session: AsyncSession, period: str, metric: str
) -> list[tuple[str, float]]:
    _, days = PERIODS[period]
    today = date.today()
    start = today - timedelta(days=days - 1)

    rows: list[tuple[str, float]] = []
    for user in await list_users(session):
        habits = await list_public_habits(session, user.id)
        if not habits:
            continue
        done = planned = marks = best = 0
        for h in habits:
            d, p = await completion_rate(session, h, start, today)
            done += d
            planned += p
            marks += d
            best = max(best, await best_streak(session, h, today))
        name = user.name or user.username or f"id{user.telegram_id}"
        if metric == "percent":
            value = round(100 * done / planned) if planned else 0
        elif metric == "streak":
            value = best
        else:
            value = marks
        rows.append((name, value))

    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def _render_board(rows, period: str, metric: str) -> str:
    period_label = PERIODS[period][0]
    suffix = {"percent": "%", "streak": " дн.", "marks": " отм."}[metric]
    lines = [f"🏆 <b>Рейтинг за {period_label}</b> ({METRICS[metric]})\n"]
    if not rows:
        lines.append("Пока нет данных — добавьте публичные привычки!")
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, value) in enumerate(rows[:15]):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {esc(name)} — {value}{suffix}")
    return "\n".join(lines)


@router.message(Command("leaderboard"))
@router.message(F.text == "🏆 Рейтинг")
async def cmd_leaderboard(message: Message, session: AsyncSession) -> None:
    rows = await _compute_board(session, "week", "percent")
    await message.answer(
        _render_board(rows, "week", "percent"),
        reply_markup=_board_kb("week", "percent").as_markup(),
    )


@router.callback_query(F.data.startswith("lb:"))
async def switch_board(callback: CallbackQuery, session: AsyncSession) -> None:
    _, period, metric = callback.data.split(":")
    rows = await _compute_board(session, period, metric)
    await callback.message.edit_text(
        _render_board(rows, period, metric),
        reply_markup=_board_kb(period, metric).as_markup(),
    )
    await callback.answer()
