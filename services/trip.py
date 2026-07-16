"""Trip module: checklist templates, categories, formatting."""
from __future__ import annotations

ITEM_CATEGORIES = {
    "docs": "📄 Документы",
    "clothes": "👕 Одежда",
    "tech": "📱 Техника",
    "hygiene": "🧴 Гигиена",
    "medicine": "💊 Аптечка",
    "food": "🍎 Еда",
    "other": "📦 Прочее",
}

CAT_ORDER = ["docs", "clothes", "tech", "hygiene", "medicine", "food", "other"]

TRIP_STATUSES = {
    "planning": "📝 Планирую",
    "packing": "🧳 Собираюсь",
    "active": "✈️ В поездке",
    "done": "✅ Завершена",
}

# (text, category, sort_order)
TEMPLATES: dict[str, tuple[str, list[tuple[str, str, int]]]] = {
    "beach": ("🏖 Пляж / море", [
        ("Паспорт", "docs", 0),
        ("Билеты / бронь", "docs", 1),
        ("Страховка", "docs", 2),
        ("Наличные / карта", "docs", 3),
        ("Купальник / плавки", "clothes", 10),
        ("Шорты", "clothes", 11),
        ("Футболки", "clothes", 12),
        ("Шлёпанцы", "clothes", 13),
        ("Солнцезащитные очки", "clothes", 14),
        ("Кепка / панама", "clothes", 15),
        ("Телефон + зарядка", "tech", 20),
        ("Пауэрбанк", "tech", 21),
        ("Наушники", "tech", 22),
        ("Солнцезащитный крем", "hygiene", 30),
        ("Зубная щётка + паста", "hygiene", 31),
        ("Шампунь / гель", "hygiene", 32),
        ("Полотенце", "hygiene", 33),
        ("Аптечка базовая", "medicine", 40),
        ("Антигистаминное", "medicine", 41),
        ("Вода в дорогу", "food", 50),
        ("Снеки", "food", 51),
    ]),
    "mountains": ("🏔 Горы / поход", [
        ("Паспорт", "docs", 0),
        ("Страховка", "docs", 1),
        ("Маршрут / карта", "docs", 2),
        ("Треккинговые ботинки", "clothes", 10),
        ("Куртка / ветровка", "clothes", 11),
        ("Термобельё", "clothes", 12),
        ("Дождевик", "clothes", 13),
        ("Шапка / бафф", "clothes", 14),
        ("Перчатки", "clothes", 15),
        ("Рюкзак", "clothes", 16),
        ("Телефон + зарядка", "tech", 20),
        ("Пауэрбанк", "tech", 21),
        ("Фонарик", "tech", 22),
        ("Солнцезащитный крем", "hygiene", 30),
        ("Влажные салфетки", "hygiene", 31),
        ("Аптечка", "medicine", 40),
        ("Пластыри для мозолей", "medicine", 41),
        ("Обезболивающее", "medicine", 42),
        ("Вода 1.5л", "food", 50),
        ("Орехи / энерго-батончики", "food", 51),
        ("Бутерброды", "food", 52),
    ]),
    "business": ("💼 Командировка", [
        ("Паспорт", "docs", 0),
        ("Билеты / бронь", "docs", 1),
        ("Рабочие документы", "docs", 2),
        ("Наличные / карта", "docs", 3),
        ("Рубашка / блузка", "clothes", 10),
        ("Брюки / юбка", "clothes", 11),
        ("Обувь деловая", "clothes", 12),
        ("Ноутбук + зарядка", "tech", 20),
        ("Телефон + зарядка", "tech", 21),
        ("Наушники", "tech", 22),
        ("Адаптер / переходник", "tech", 23),
        ("Зубная щётка + паста", "hygiene", 30),
        ("Дезодорант", "hygiene", 31),
        ("Аптечка", "medicine", 40),
    ]),
    "city": ("🏙 Город / уикенд", [
        ("Паспорт", "docs", 0),
        ("Билеты / бронь", "docs", 1),
        ("Наличные / карта", "docs", 2),
        ("Удобная обувь", "clothes", 10),
        ("Куртка по погоде", "clothes", 11),
        ("Сменная одежда", "clothes", 12),
        ("Телефон + зарядка", "tech", 20),
        ("Пауэрбанк", "tech", 21),
        ("Наушники", "tech", 22),
        ("Зубная щётка + паста", "hygiene", 30),
        ("Аптечка", "medicine", 40),
        ("Вода / снеки", "food", 50),
    ]),
}


def format_checklist(items: list, trip_name: str) -> str:
    if not items:
        return f"🧳 <b>{trip_name}</b>\n\nСписок пуст. Добавь пункты или выбери шаблон."

    grouped: dict[str, list] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    checked = sum(1 for i in items if i.checked)
    total = len(items)
    pct = int(checked / total * 100) if total else 0
    bar_filled = pct // 10
    bar = "▓" * bar_filled + "░" * (10 - bar_filled)

    lines = [
        f"🧳 <b>{trip_name}</b>",
        f"{bar} {checked}/{total} ({pct}%)\n",
    ]

    for cat in CAT_ORDER:
        cat_items = grouped.get(cat)
        if not cat_items:
            continue
        lines.append(f"<b>{ITEM_CATEGORIES[cat]}</b>:")
        for item in sorted(cat_items, key=lambda x: x.sort_order):
            mark = "✅" if item.checked else "⬜"
            lines.append(f"  {mark} {item.text}")
        lines.append("")

    return "\n".join(lines)
