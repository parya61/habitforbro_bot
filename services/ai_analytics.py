"""AI-аналитика: сбор контекста пользователя и запрос к DeepSeek API."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from dataclasses import dataclass

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    list_habits,
    list_diary_entries,
    list_goals,
    list_achieved_goals,
    list_tea_sessions,
)
from services.stats import user_stats
from services.streaks import current_streak, best_streak
from utils import display_name

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """Ты — аналитик привычек и личного развития в боте «Дневник привычек».
Тебя зовут Керя. Ты спокойный, прямой и по-доброму честный. Говоришь на «ты», просто и тепло.

Тебе дан полный контекст пользователя: привычки, серии, дневник, цели, статистика.
Твоя задача — помочь человеку стать дисциплинированнее и ближе к его целям.

Правила:
- Анализируй факты: регулярность, пропуски, серии, настроение из дневника, прогресс по целям.
- Ищи закономерности: когда пропускает, что мешает, что помогает.
- Давай конкретные, применимые советы — не абстрактные мотивашки.
- Не читай нравоучений. Не стыди. Не льсти.
- Если видишь реальный прогресс — отметь его коротко, без восторгов.
- Если видишь проблему — скажи прямо и предложи одно конкретное действие.
- Отвечай коротко (до 1500 символов). Не лей воду.
- Помни: ты видишь только данные этого конкретного пользователя. Никогда не упоминай данные других.
- Общайся по-русски."""


async def build_user_context(session: AsyncSession, user: User) -> str:
    """Собирает полный контекст пользователя для AI-анализа."""
    today = date.today()
    name = display_name(user)
    lines = [f"Пользователь: {name}\n"]

    # Статистика
    stats = await user_stats(session, user.id)
    lines.append("== СТАТИСТИКА ==")
    lines.append(f"Активных привычек: {stats.active_habits}")
    lines.append(f"За неделю: {stats.week_done}/{stats.week_planned} ({stats.week_percent}%)")
    lines.append(f"За месяц: {stats.month_done}/{stats.month_planned} ({stats.month_percent}%)")
    lines.append(f"Рекорд серии: {stats.record_streak} дн.")
    lines.append("")

    # Привычки с сериями
    habits = await list_habits(session, user.id)
    if habits:
        lines.append("== ПРИВЫЧКИ ==")
        for h in habits:
            cur = await current_streak(session, h, None)
            best = await best_streak(session, h, None)
            desc = f" — {h.description}" if h.description else ""
            target_str = ""
            if h.type == "quantitative" and h.target:
                target_str = f" (цель: {h.target} {h.unit or ''}/день)"
            freq_str = ""
            if h.frequency != "daily":
                freq_str = f" [{h.frequency}"
                if h.freq_value:
                    freq_str += f": {h.freq_value}"
                freq_str += "]"
            lines.append(
                f"- {h.emoji} {h.title}{desc}{target_str}{freq_str} | "
                f"серия: {cur} дн., рекорд: {best} дн."
            )
        lines.append("")

    # Цели
    for level, level_name in [
        ("life", "На жизнь"), ("year", "На год"),
        ("month", "На месяц"), ("tomorrow", "На завтра"),
    ]:
        goals = await list_goals(session, user.id, level)
        if goals:
            if level == "life":
                lines.append("== ЦЕЛИ ==")
            lines.append(f"--- {level_name} ---")
            for g in goals:
                lines.append(f"- {g.title}")

    achieved = await list_achieved_goals(session, user.id, limit=10)
    if achieved:
        lines.append("--- Достигнутые (последние) ---")
        for g in achieved:
            d = g.achieved_at.strftime("%d.%m") if g.achieved_at else "?"
            lines.append(f"- ✅ {g.title} ({d})")
    lines.append("")

    # Дневник (последние 14 дней)
    diary = await list_diary_entries(session, user.id, limit=14)
    if diary:
        lines.append("== ДНЕВНИК (последние записи) ==")
        for entry in diary:
            mood = f" [{entry.mood}]" if entry.mood else ""
            text = entry.text[:300]
            lines.append(f"{entry.entry_date}{mood}: {text}")
        lines.append("")

    return "\n".join(lines)


@dataclass
class AiResponse:
    text: str
    ok: bool
    error: str | None = None


async def ask_deepseek(
    api_key: str,
    messages: list[dict[str, str]],
) -> AiResponse:
    """Отправляет запрос к DeepSeek API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": 1500,
        "temperature": 0.7,
    }

    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                DEEPSEEK_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("DeepSeek API error %s: %s", resp.status, body[:500])
                    return AiResponse(text="", ok=False, error=f"API error {resp.status}")
                data = await resp.json()
                text = data["choices"][0]["message"]["content"]
                return AiResponse(text=text, ok=True)
    except Exception as e:
        logger.exception("DeepSeek request failed")
        return AiResponse(text="", ok=False, error=str(e))
