"""Grocery module: seed data, formatting, store/category constants."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

GROCERY_CATEGORIES = {
    "meat": "🥩 Мясо",
    "fish": "🐟 Рыба",
    "dairy": "🥛 Молочное",
    "grain": "🌾 Крупы",
    "vegetable": "🥔 Овощи",
    "greens": "🌿 Зелень",
    "fruit": "🍎 Фрукты",
    "bread": "🍞 Хлеб",
    "canned": "🥫 Консервы",
    "household": "🧴 Бытовое",
    "sweets": "🍬 Сладкое",
    "spice": "🧂 Специи",
}

STORE_NAMES = {
    "рынок": "🏪 Рынок",
    "лента": "🏪 Лента",
    "пятёрочка": "🏪 Пятёрочка",
}
STORE_ORDER = ["рынок", "лента", "пятёрочка"]
STORE_CODES = {"r": "рынок", "l": "лента", "p": "пятёрочка"}
CODE_BY_STORE = {v: k for k, v in STORE_CODES.items()}

FREQ_OPTIONS = [
    (3, "3 дня"),
    (7, "7 дней"),
    (14, "14 дней"),
    (30, "30 дней"),
]

# (name, category, icon, store, qty, freq_days, for_whom, sort_order)
GROCERY_SEED: list[tuple[str, str, str, str, str, int, str, int]] = [
    # Мясо
    ("Куриная грудка", "meat", "🥩", "рынок", "2 кг", 7, "all", 0),
    ("Куриные бёдра", "meat", "🥩", "рынок", "1.5 кг", 7, "all", 1),
    ("Фарш куриный", "meat", "🥩", "рынок", "1 кг", 7, "all", 2),
    ("Фарш говяжий", "meat", "🥩", "рынок", "1 кг", 7, "all", 3),
    ("Говядина мякоть", "meat", "🥩", "рынок", "1.5 кг", 7, "all", 4),
    ("Говядина на кости", "meat", "🥩", "рынок", "1 кг", 14, "all", 5),
    ("Индейка филе", "meat", "🥩", "рынок", "1 кг", 14, "all", 6),
    # Рыба
    ("Рыба красная", "fish", "🐟", "рынок", "0.5 кг", 14, "all", 10),
    ("Рыба на суп", "fish", "🐟", "рынок", "0.5 кг", 14, "all", 11),
    ("Креветки", "fish", "🐟", "рынок", "0.5 кг", 14, "all", 12),
    # Молочное
    ("Молоко", "dairy", "🥛", "пятёрочка", "1 л", 3, "all", 20),
    ("Сметана", "dairy", "🥛", "пятёрочка", "200 г", 5, "all", 21),
    ("Творог", "dairy", "🥛", "лента", "1 кг", 7, "all", 22),
    ("Йогурт", "dairy", "🥛", "лента", "1 кг", 7, "all", 23),
    ("Сыр твёрдый", "dairy", "🧀", "лента", "300 г", 7, "all", 24),
    ("Сливочное масло", "dairy", "🧈", "лента", "180 г", 14, "all", 25),
    ("Яйца", "dairy", "🥚", "лента", "20 шт", 7, "all", 26),
    ("Кефир", "dairy", "🥛", "пятёрочка", "1 л", 5, "all", 27),
    # Крупы
    ("Гречка", "grain", "🌾", "лента", "1 кг", 30, "all", 30),
    ("Рис басмати", "grain", "🌾", "лента", "1 кг", 30, "all", 31),
    ("Булгур", "grain", "🌾", "лента", "1 кг", 30, "all", 32),
    ("Геркулес", "grain", "🌾", "лента", "0.5 кг", 30, "me", 33),
    ("Кукурузная крупа", "grain", "🌾", "лента", "0.5 кг", 30, "all", 34),
    # Овощи
    ("Картошка", "vegetable", "🥔", "лента", "2 кг", 7, "all", 40),
    ("Батат", "vegetable", "🍠", "лента", "1 кг", 7, "all", 41),
    ("Помидоры", "vegetable", "🍅", "пятёрочка", "1.5 кг", 5, "all", 42),
    ("Огурцы", "vegetable", "🥒", "пятёрочка", "1.5 кг", 5, "all", 43),
    ("Лук белый", "vegetable", "🧅", "лента", "4 шт", 7, "all", 44),
    ("Лук красный", "vegetable", "🧅", "лента", "2 шт", 7, "all", 45),
    ("Чеснок", "vegetable", "🧄", "лента", "300 г", 14, "all", 46),
    ("Болгарский перец", "vegetable", "🫑", "пятёрочка", "3 шт", 5, "all", 47),
    ("Свёкла", "vegetable", "🥔", "лента", "2 шт", 7, "all", 48),
    ("Шампиньоны", "vegetable", "🍄", "пятёрочка", "500 г", 7, "all", 49),
    ("Кабачки", "vegetable", "🥒", "пятёрочка", "2 шт", 7, "all", 50),
    ("Морковь", "vegetable", "🥕", "лента", "1 кг", 7, "all", 51),
    # Зелень
    ("Петрушка", "greens", "🌿", "пятёрочка", "1 пучок", 5, "all", 55),
    ("Укроп", "greens", "🌿", "пятёрочка", "1 пучок", 5, "all", 56),
    ("Шпинат", "greens", "🌿", "пятёрочка", "1 пучок", 7, "all", 57),
    # Фрукты
    ("Бананы", "fruit", "🍌", "пятёрочка", "1 кг", 3, "all", 60),
    ("Яблоки", "fruit", "🍎", "пятёрочка", "5 шт", 7, "all", 61),
    ("Лимоны", "fruit", "🍋", "пятёрочка", "3 шт", 7, "all", 62),
    # Хлеб
    ("Хлеб", "bread", "🍞", "пятёрочка", "1 шт", 3, "all", 65),
    ("Тортилья", "bread", "🫓", "лента", "1 уп", 7, "all", 66),
    # Консервы
    ("Оливки", "canned", "🫒", "лента", "1 банка", 14, "all", 70),
    ("Кукуруза консерв.", "canned", "🌽", "лента", "1 банка", 14, "all", 71),
    ("Томатная паста", "canned", "🥫", "лента", "1 шт", 30, "all", 72),
    # Бытовое
    ("Туалетная бумага", "household", "🧻", "лента", "1 уп", 30, "all", 80),
    # Сладкое (только для жены)
    ("Сладкое", "sweets", "🍬", "пятёрочка", "", 7, "wife", 90),
    # Специи
    ("Растит. масло", "spice", "🫙", "лента", "1 л", 30, "all", 95),
]


async def ensure_seeded(session: AsyncSession, user_id: int) -> None:
    from db.grocery_queries import count_items

    if await count_items(session, user_id) > 0:
        return

    from db.models import GroceryItem

    for name, cat, icon, store, qty, freq, for_whom, sort in GROCERY_SEED:
        session.add(GroceryItem(
            user_id=user_id,
            name=name,
            category=cat,
            icon=icon,
            usual_store=store,
            usual_qty=qty,
            buy_freq_days=freq,
            for_whom=for_whom,
            sort_order=sort,
        ))
    await session.commit()


def format_shopping_list(
    items_by_store: dict[str, list],
    total: int,
) -> str:
    if not items_by_store:
        return "Всё куплено! Список пуст."

    lines = [f"📝 <b>Список покупок</b> ({total} поз.)\n"]
    for store in STORE_ORDER:
        items = items_by_store.get(store)
        if not items:
            continue
        lines.append(f"<b>{STORE_NAMES[store]}</b>:")
        for item in items:
            qty = f" — {item.usual_qty}" if item.usual_qty else ""
            whom = " 👩" if item.for_whom == "wife" else ""
            lines.append(f"  {item.icon} {item.name}{qty}{whom}")
        lines.append("")

    return "\n".join(lines)
