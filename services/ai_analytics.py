"""AI-аналитика: сбор контекста пользователя и запрос к DeepSeek API."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from dataclasses import dataclass

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    get_tea_profile,
    list_habits,
    list_diary_entries,
    list_goals,
    list_achieved_goals,
    list_tea_collection,
    list_tea_sessions,
    list_teaware_items,
    count_tea_sessions,
)
from services.stats import user_stats
from services.streaks import current_streak, best_streak
from utils import display_name

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """Ты — личный аналитик привычек, финансов и чая в боте «Дневник привычек».
Тебя зовут Керя. Ты спокойный, прямой и по-доброму честный. Говоришь на «ты», просто и тепло.

Тебе дан полный контекст пользователя: привычки, серии, дневник, цели, статистика, финансы, продукты, чай.
Твоя задача — помочь человеку стать дисциплинированнее, ближе к целям и финансово осознаннее.

Правила:
- Анализируй факты: регулярность, пропуски, серии, настроение из дневника, прогресс по целям.
- Анализируй финансы: расходы по категориям, тренды, аномалии, соотношение доход/расход.
- Ищи закономерности: когда пропускает привычки, куда уходят деньги, что можно оптимизировать.
- Давай конкретные, применимые советы с цифрами — не абстрактные мотивашки.
- Не читай нравоучений. Не стыди. Не льсти. Не морализируй по поводу трат.
- Если видишь аномалию в расходах — скажи прямо: «кафе +40% к среднему» с конкретикой.
- Чай: уважай чайную культуру. Замечай паттерны (какие виды чаще, как меняются оценки, расход коллекции). Не упрощай тему.
- Фиды: тебе доступен собранный контент из Telegram-каналов и YouTube-видео (с транскриптами). Используй эту информацию если пользователь спрашивает о чём-то что может быть в его подписках. Суммируй, анализируй, находи полезное.
- Философия и мораль: у тебя есть база знаний по книгам хозяина (Достоевский, Сенека, Марк Аврелий, Франкл, Ильин, Библия, Несвятые святые). При жизненных, моральных, экзистенциальных вопросах — опирайся на эти источники. Показывай разные ракурсы, цитируй авторов. Не давай плоских ответов — помогай думать.
- Чай: у тебя есть чайная база знаний (от Ча Цзин до Похлёбкина). Различай типы, традиции, историю. Используй при любых вопросах о чае.
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

    # Продукты
    await _append_grocery_context(session, user, today, lines)

    # Чай
    await _append_tea_context(session, user, lines)

    # Кафе
    await _append_cafe_context(session, user, lines)

    # Подарки
    await _append_gift_context(session, user, today, lines)

    # Поездки
    await _append_trip_context(session, user, lines)

    # Фиды (Telegram-каналы, YouTube)
    await _append_feed_context(session, user, lines)

    # База знаний (философия, чай)
    _append_knowledge(lines)

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


async def _append_tea_context(
    session: AsyncSession, user: User, lines: list[str]
) -> None:
    total = await count_tea_sessions(session, user.id)
    if total == 0:
        return

    from handlers.tea import TEA_TYPES, TEA_TYPE_EMOJI, CHA_QI_OPTIONS

    lines.append("== ЧАЙ ==")

    profile = await get_tea_profile(session, user.id)
    if profile:
        if profile.tea_story:
            lines.append(f"Путь к чаю: {profile.tea_story[:200]}")
        if profile.favorite_types:
            fav = [TEA_TYPES.get(t, t) for t in profile.favorite_types.split(",") if t]
            lines.append(f"Любимые виды: {', '.join(fav)}")
        if profile.taste_preferences:
            lines.append(f"Вкусовые предпочтения: {profile.taste_preferences}")

    lines.append(f"Всего чаепитий: {total}")

    sessions = await list_tea_sessions(session, user.id, limit=15)
    if sessions:
        type_counts: dict[str, int] = {}
        rating_sum = 0
        rating_count = 0
        tags_count: dict[str, int] = {}
        qi_count: dict[str, int] = {}

        for s in sessions:
            t = TEA_TYPES.get(s.tea_type, s.tea_type)
            type_counts[t] = type_counts.get(t, 0) + 1
            if s.rating:
                rating_sum += s.rating
                rating_count += 1
            if s.taste_tags:
                for tag in s.taste_tags.split(","):
                    tag = tag.strip()
                    if tag:
                        tags_count[tag] = tags_count.get(tag, 0) + 1
            if s.cha_qi and s.cha_qi != "none":
                qi_label = CHA_QI_OPTIONS.get(s.cha_qi, s.cha_qi)
                qi_count[qi_label] = qi_count.get(qi_label, 0) + 1

        if rating_count:
            avg = rating_sum / rating_count
            lines.append(f"Средняя оценка (последние): {avg:.1f}/10")

        top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:5]
        lines.append("По видам (последние): " + ", ".join(f"{t} ({c})" for t, c in top_types))

        if tags_count:
            top_tags = sorted(tags_count.items(), key=lambda x: -x[1])[:6]
            lines.append("Частые вкусы: " + ", ".join(f"{t} ({c})" for t, c in top_tags))

        if qi_count:
            qi_top = sorted(qi_count.items(), key=lambda x: -x[1])[:3]
            lines.append("Ча ци: " + ", ".join(f"{q} ({c})" for q, c in qi_top))

        lines.append("Последние сессии:")
        for s in sessions[:7]:
            d = s.session_date.strftime("%d.%m")
            emoji = TEA_TYPE_EMOJI.get(s.tea_type, "🍵")
            t = TEA_TYPES.get(s.tea_type, s.tea_type)
            r = f" [{s.rating}/10]" if s.rating else ""
            tags = ""
            if s.taste_tags:
                tags = f" ({s.taste_tags[:60]})"
            lines.append(f"  {d} {emoji} {s.tea_name} ({t}){r}{tags}")

    collection = await list_tea_collection(session, user.id)
    if collection:
        lines.append(f"Коллекция: {len(collection)} чаёв")
        for item in collection[:8]:
            t = TEA_TYPES.get(item.tea_type, item.tea_type)
            w = f" {item.remaining_grams}г" if item.remaining_grams else ""
            v = f" ({item.vendor})" if item.vendor else ""
            lines.append(f"  🍵 {item.tea_name} ({t}){w}{v}")

    teaware = await list_teaware_items(session, user.id)
    if teaware:
        lines.append(f"Посуда: {len(teaware)} предметов")
        for tw in teaware[:5]:
            vol = f" {tw.volume_ml}мл" if tw.volume_ml else ""
            lines.append(f"  🫖 {tw.name}{vol}")

    lines.append("")


async def _append_cafe_context(
    session: AsyncSession, user: User, lines: list[str]
) -> None:
    from db.cafe_queries import count_cafes, list_visits, top_cafes
    from services.finance import fmt_money

    total = await count_cafes(session, user.id)
    if total == 0:
        return

    lines.append("== КАФЕ ==")
    lines.append(f"Всего мест: {total}")

    top = await top_cafes(session, user.id, limit=5)
    if top:
        lines.append("Топ кафе:")
        for cafe, visits, avg_r, avg_s in top:
            r = f" ⭐{avg_r:.1f}" if avg_r else ""
            s = f" ~{fmt_money(avg_s)}" if avg_s else ""
            lines.append(f"  ☕ {cafe.name}{r}{s} — {visits} виз.")

    visits = await list_visits(session, user.id, limit=7)
    if visits:
        lines.append("Последние визиты:")
        for v in visits:
            d = v.visit_date.strftime("%d.%m")
            name = v.cafe.name if v.cafe else "?"
            r = f" ⭐{v.rating}" if v.rating else ""
            s = f" {fmt_money(v.spent)}" if v.spent else ""
            dish = f" — {v.dish}" if v.dish else ""
            lines.append(f"  {d} ☕ {name}{r}{s}{dish}")

    lines.append("")


async def _append_gift_context(
    session: AsyncSession, user: User, today: date, lines: list[str]
) -> None:
    from db.gift_queries import count_persons, list_all_ideas, list_persons
    from services.gift import (
        REL_LABELS,
        days_label,
        upcoming_birthdays,
        upcoming_holidays,
    )

    total = await count_persons(session, user.id)
    if total == 0:
        return

    lines.append("== ПОДАРКИ ==")
    persons = await list_persons(session, user.id)
    lines.append(f"Людей: {total}")

    bdays = upcoming_birthdays(persons, today, days_ahead=30)
    holidays = upcoming_holidays(today, days_ahead=30)

    if holidays:
        for hdate, hname, delta in holidays:
            lines.append(f"  {hname} — {days_label(delta)}")

    if bdays:
        for person, bdate, delta, age in bdays:
            rel = REL_LABELS.get(person.rel_type, "")
            lines.append(f"  🎂 {person.name} ({rel}) — {age} лет, {days_label(delta)}")

    ideas = await list_all_ideas(session, user.id)
    if ideas:
        lines.append(f"Идей подарков: {len(ideas)}")
        for g in ideas[:5]:
            pname = g.person.name if g.person else "?"
            lines.append(f"  💡 {g.title} → {pname}")

    lines.append("")


async def _append_trip_context(
    session: AsyncSession, user: User, lines: list[str]
) -> None:
    from db.trip_queries import list_trips
    from services.trip import TRIP_STATUSES

    trips = await list_trips(session, user.id, active_only=True)
    if not trips:
        return

    lines.append("== ПОЕЗДКИ ==")
    for trip in trips:
        status = TRIP_STATUSES.get(trip.status, trip.status)
        items = trip.items or []
        checked = sum(1 for i in items if i.checked)
        total = len(items)
        pct = f" ({checked}/{total})" if total else ""
        dest = f" → {trip.destination}" if trip.destination else ""
        lines.append(f"  {status} {trip.name}{dest}{pct}")
        unchecked = [i.text for i in items if not i.checked][:5]
        if unchecked:
            lines.append(f"    Осталось: {', '.join(unchecked)}")

    lines.append("")


async def _append_grocery_context(
    session: AsyncSession, user: User, today: date, lines: list[str]
) -> None:
    from db.grocery_queries import count_items, group_by_store, list_due_items
    from services.grocery import STORE_NAMES

    total = await count_items(session, user.id)
    if total == 0:
        return

    due = await list_due_items(session, user.id, today)
    lines.append("== ПРОДУКТЫ ==")
    lines.append(f"Каталог: {total} позиций.")
    lines.append(f"Пора купить: {len(due)} позиций.")

    if due:
        grouped = group_by_store(due)
        parts = []
        for store, items in grouped.items():
            name = STORE_NAMES.get(store, store)
            parts.append(f"{name}: {len(items)}")
        lines.append(f"По магазинам: {', '.join(parts)}.")

        overdue = []
        for item in due:
            if item.last_bought:
                days = (today - item.last_bought).days
                if days > item.buy_freq_days * 2:
                    overdue.append(f"{item.icon} {item.name} ({days} дн. назад)")
        if overdue:
            lines.append(f"Давно не покупали: {', '.join(overdue[:5])}.")

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


async def _append_feed_context(
    session: AsyncSession, user: User, lines: list[str]
) -> None:
    from db.feed_queries import list_sources, recent_items

    sources = await list_sources(session, user.id)
    if not sources:
        return

    lines.append("\n== СОБРАННЫЙ КОНТЕНТ (Telegram/YouTube) ==")

    tg_src = [s for s in sources if s.source_type == "telegram"]
    yt_src = [s for s in sources if s.source_type == "youtube"]
    lines.append(f"Источников: {len(tg_src)} Telegram, {len(yt_src)} YouTube")
    lines.append("Каналы: " + ", ".join(s.title for s in sources))

    items = await recent_items(session, user.id, limit=15)
    if not items:
        lines.append("Пока нет собранного контента.")
        return

    lines.append(f"\nПоследние {len(items)} записей:")
    for item in items:
        src_name = item.source.title if item.source else "?"
        date_str = item.published_at.strftime("%d.%m") if item.published_at else ""
        icon = "TG" if item.item_type == "post" else "YT"

        title = (item.title or "")[:100]
        lines.append(f"\n[{icon}] {date_str} | {src_name} | {title}")

        text = item.text or ""
        if len(text) > 800:
            text = text[:800] + "..."
        if text:
            lines.append(text)


_knowledge_cache: dict[str, str] = {}


def _append_knowledge(lines: list[str]) -> None:
    from pathlib import Path

    kb_dir = Path(__file__).resolve().parent.parent / "data" / "knowledge"
    if not kb_dir.exists():
        return

    for md_file in sorted(kb_dir.glob("*.md")):
        name = md_file.stem
        if name not in _knowledge_cache:
            try:
                _knowledge_cache[name] = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
        content = _knowledge_cache[name]
        if content:
            lines.append(f"\n== БАЗА ЗНАНИЙ: {name.upper()} ==")
            lines.append(content)
