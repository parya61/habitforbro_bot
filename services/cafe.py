"""Cafe module: cuisine types, price levels, formatting."""
from __future__ import annotations

from services.finance import fmt_money

CUISINE_TYPES = [
    ("🍕", "Итальянская"),
    ("🍣", "Японская"),
    ("🥟", "Грузинская"),
    ("🌮", "Мексиканская"),
    ("🍜", "Азиатская"),
    ("🥩", "Мясная"),
    ("🐟", "Рыбная"),
    ("🥗", "Здоровая"),
    ("☕", "Кофейня"),
    ("🍺", "Бар"),
    ("🍰", "Кондитерская"),
    ("🍽", "Смешанная"),
]

PRICE_LEVELS = {
    1: "💰 Бюджетно",
    2: "💰💰 Средне",
    3: "💰💰💰 Дорого",
}


def fmt_rating(rating: float | None) -> str:
    if rating is None:
        return "—"
    full = int(rating)
    half = rating - full >= 0.5
    stars = "⭐" * full + ("½" if half else "")
    return f"{stars} {rating:.1f}"


def fmt_price_level(level: int | None) -> str:
    if level is None:
        return ""
    return "💰" * level


def format_cafe_card(cafe, visit_count: int, avg_rating: float | None, avg_spent: float | None) -> str:
    lines = [f"☕ <b>{cafe.name}</b>"]
    if cafe.address:
        lines.append(f"📍 {cafe.address}")
    if cafe.cuisine:
        lines.append(f"🍽 {cafe.cuisine}")
    if cafe.price_level:
        lines.append(f"{fmt_price_level(cafe.price_level)}")
    if visit_count > 0:
        lines.append(f"📊 Визитов: {visit_count}")
        if avg_rating is not None:
            lines.append(f"⭐ Средняя оценка: {avg_rating:.1f}/10")
        if avg_spent is not None:
            lines.append(f"💸 Средний чек: {fmt_money(avg_spent)}")
    elif cafe.is_wishlist:
        lines.append("📌 В вишлисте")
    if cafe.notes:
        lines.append(f"📝 {cafe.notes}")
    return "\n".join(lines)
