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

SYSTEM_PROMPT = """Ты — личный аналитик привычек и финансов в боте «Дневник привычек».
Тебя зовут Керя. Ты спокойный, прямой и по-доброму честный. Говоришь на «ты», просто и тепло.

Тебе дан полный контекст пользователя: привычки, серии, дневник, цели, статистика, финансы.
Твоя задача — помочь человеку стать дисциплинированнее, ближе к целям и финансово осознаннее.

Правила:
- Анализируй факты: регулярность, пропуски, серии, настроение из дневника, прогресс по целям.
- Анализируй финансы: расходы по категориям, тренды, аномалии, соотношение доход/расход.
- Ищи закономерности: когда пропускает привычки, куда уходят деньги, что можно оптимизировать.
- Давай конкретные, применимые советы с цифрами — не абстрактные мотивашки.
- Не читай нравоучений. Не стыди. Не льсти. Не морализируй по поводу трат.
- Если видишь аномалию в расходах — скажи прямо: «кафе +40% к среднему» с конкретикой.
- Отвечай коротко (до 1500 символов). Не лей воду.
- Помни: ты видишь только данные этого конкретного пользователя.
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

    # Финансы
    await _append_finance_context(session, user, today, lines)

    return "\n".join(lines)


async def _append_finance_context(
    session: AsyncSession, user: User, today: date, lines: list[str]
) -> None:
    from db.finance_queries import (
        category_totals,
        count_categories,
        list_transactions,
        monthly_totals,
    )
    from services.finance import MONTH_NAMES, fmt_money

    if await count_categories(session, user.id) == 0:
        return

    cur_month = f"{today.year}-{today.month:02d}"
    income, expenses = await monthly_totals(session, user.id, cur_month)

    if not income and not expenses:
        return

    lines.append("== ФИНАНСЫ ==")
    month_name = MONTH_NAMES[today.month]
    balance = income - expenses
    lines.append(f"Текущий месяц ({month_name} {today.year}):")
    lines.append(f"  Доходы:  +{fmt_money(income)}")
    lines.append(f"  Расходы: −{fmt_money(expenses)}")
    sign = "+" if balance >= 0 else ""
    lines.append(f"  Баланс:  {sign}{fmt_money(abs(balance))}")

    cats = await category_totals(session, user.id, cur_month, "expense")
    if cats:
        lines.append("Расходы по категориям:")
        for icon, name, total in cats:
            pct = int(total / expenses * 100) if expenses > 0 else 0
            lines.append(f"  {icon} {name}: {fmt_money(total)} ({pct}%)")

    prev_m = today.month - 1
    prev_y = today.year
    if prev_m == 0:
        prev_m = 12
        prev_y -= 1
    prev_month = f"{prev_y}-{prev_m:02d}"
    prev_inc, prev_exp = await monthly_totals(session, user.id, prev_month)
    if prev_exp > 0:
        diff = expenses - prev_exp
        diff_pct = int(diff / prev_exp * 100)
        prev_name = MONTH_NAMES[prev_m]
        lines.append(
            f"Сравнение: расходы {month_name} vs {prev_name}: "
            f"{'+' if diff >= 0 else ''}{diff_pct}% ({'+' if diff >= 0 else ''}{fmt_money(abs(diff))})"
        )

        prev_cats = await category_totals(session, user.id, prev_month, "expense")
        prev_map = {name: total for _, name, total in prev_cats}
        anomalies = []
        for icon, name, total in cats:
            prev_total = prev_map.get(name, 0)
            if prev_total > 0:
                cat_diff_pct = int((total - prev_total) / prev_total * 100)
                if cat_diff_pct > 30:
                    anomalies.append(f"  {icon} {name}: +{cat_diff_pct}% к прошлому месяцу")
                elif cat_diff_pct < -30:
                    anomalies.append(f"  {icon} {name}: {cat_diff_pct}% к прошлому месяцу")
        if anomalies:
            lines.append("Аномалии:")
            lines.extend(anomalies)

    txs = await list_transactions(session, user.id, limit=10)
    if txs:
        lines.append("Последние операции:")
        for tx in txs:
            d = tx.tx_date.strftime("%d.%m")
            s = "+" if tx.tx_type == "income" else "−"
            cat_name = tx.category.name if tx.category else "?"
            desc = tx.merchant or cat_name
            lines.append(f"  {d} {s}{fmt_money(tx.amount)} {desc} ({cat_name})")

    lines.append("")


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
