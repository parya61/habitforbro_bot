"""Раздел «Призы»: текущий приз, лидер месяца, история победителей, получение VPN."""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger("habits-bot")

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
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

    lines = ["\U0001f381 <b>Призы</b>\n"]

    # Текущий месяц
    prize = await get_prize(session, current_month)
    if prize:
        lines.append(f"<b>Приз месяца ({current_month}):</b>")
        lines.append(f"\U0001f381 {esc(prize.description)}")
        if prize.winner_user_id:
            medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
            winners = [
                (prize.winner, prize.winner_user_id),
                (prize.winner_2, prize.winner_2_user_id),
                (prize.winner_3, prize.winner_3_user_id),
            ]
            lines.append("\n<b>Победители:</b>")
            for i, (w, wid) in enumerate(winners):
                if w:
                    lines.append(f"{medals[i]} {esc(display_name(w))}")
        else:
            leader, rate = await _current_leader(session, month_start, today)
            if leader:
                lines.append(
                    f"\U0001f4ca Лидер сейчас: {esc(display_name(leader))} ({round(rate * 100)}%)"
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
@router.message(F.text == "\U0001f381 Призы")
async def cmd_prizes(message: Message, session: AsyncSession, user: User) -> None:
    await show_prizes(message, session, user)


@router.callback_query(F.data.startswith("claim_vpn:"))
async def claim_vpn_prize(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    """Обработка кнопки 'Забрать приз' — проверяет, что нажавший является победителем."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    month_str = parts[1]
    place = int(parts[2])

    prize = await get_prize(session, month_str)
    if not prize:
        await callback.answer("Приз не найден", show_alert=True)
        return

    winner_map = {
        1: prize.winner_user_id,
        2: prize.winner_2_user_id,
        3: prize.winner_3_user_id,
    }

    if winner_map.get(place) != user.id:
        logger.info(
            "PRIZE | Попытка забрать чужой приз: tg=%d, месяц=%s, место=%d",
            user.telegram_id, month_str, place,
        )
        await callback.answer(
            "Этот приз предназначен другому победителю \U0001f60a",
            show_alert=True,
        )
        return

    # Отдаём ссылку на VPN-страницу
    url_index = place - 1
    if url_index < len(config.vpn_prize_urls):
        url = config.vpn_prize_urls[url_index]
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        places_text = ["1 место", "2 место", "3 место"]
        text = (
            f"{medals[url_index]} <b>Поздравляем с {places_text[url_index]}!</b>\n\n"
            f"\U0001f381 Твой приз — VPN Helsinki (\U0001f1eb\U0001f1ee Финляндия)\n\n"
            f"\U0001f517 <b>Открой ссылку</b> — там QR-код и инструкция:\n{url}\n\n"
            f"VPN действует до конца следующего месяца.\n"
            f"Спасибо, что держишь привычки! \U0001f4aa"
        )
        try:
            await callback.message.chat.bot.send_message(
                user.telegram_id, text, disable_web_page_preview=True
            )
            await callback.answer("Приз отправлен тебе в личку! \U0001f389", show_alert=True)
            logger.info(
                "PRIZE | Приз выдан: tg=%d (%s), месяц=%s, место=%d, url=%s",
                user.telegram_id, display_name(user), month_str, place, url,
            )
        except Exception as e:
            logger.error(
                "PRIZE | Не удалось отправить приз: tg=%d, ошибка=%s",
                user.telegram_id, e,
            )
            await callback.answer(
                "Не получилось отправить в ЛС. Напиши боту /start и попробуй снова.",
                show_alert=True,
            )
    else:
        await callback.answer("Ссылка на приз пока не настроена", show_alert=True)
