"""Finance Manager: парсинг ввода, форматирование, seed-данные."""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession


MONTH_NAMES = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def fmt_money(amount: float) -> str:
    if amount == int(amount):
        s = f"{int(amount):,}".replace(",", " ")
    else:
        s = f"{amount:,.2f}".replace(",", " ")
    return f"{s}₽"


def parse_amount_merchant(text: str) -> tuple[float | None, str | None]:
    text = text.strip()
    if not text:
        return None, None

    match = re.search(r"(\d[\d\s]*\d?[.,]?\d*)", text)
    if not match:
        return None, None

    num_str = match.group(1).replace(" ", "").replace(",", ".")
    try:
        amount = float(num_str)
    except ValueError:
        return None, None

    if amount <= 0:
        return None, None

    rest = (text[: match.start()] + text[match.end() :]).strip().strip("—–-").strip()
    return amount, rest or None


# ---- Seed data ----

DEFAULT_EXPENSE_CATS: list[tuple[str, str]] = [
    ("\U0001f6d2", "Продукты"),
    ("\U0001f37d", "Кафе"),
    ("⛽", "Авто"),
    ("\U0001f457", "Одежда"),
    ("\U0001f4f1", "Связь и подписки"),
    ("\U0001f3e0", "ЖКХ"),
    ("\U0001f48a", "Здоровье"),
    ("\U0001f3cb", "Спорт и уход"),
    ("\U0001f393", "Образование"),
    ("\U0001f5a5", "IT и серверы"),
    ("\U0001f375", "Чай"),
    ("\U0001f381", "Подарки"),
    ("\U0001f695", "Транспорт"),
    ("\U0001f4e6", "Маркетплейсы"),
    ("\U0001f4b8", "Переводы"),
    ("\U0001f4cc", "Прочее"),
]

DEFAULT_INCOME_CATS: list[tuple[str, str]] = [
    ("\U0001f4bc", "Зарплата"),
    ("\U0001f4b0", "Кэшбэк"),
    ("\U0001f4c8", "Инвестиции"),
    ("\U0001f4cc", "Прочий доход"),
]

DEFAULT_MERCHANT_RULES: list[tuple[str, str]] = [
    ("пятёрочка", "Продукты"), ("пятерочка", "Продукты"),
    ("лента", "Продукты"), ("вкусвилл", "Продукты"),
    ("магнит", "Продукты"), ("перекрёсток", "Продукты"),
    ("перекресток", "Продукты"), ("самокат", "Продукты"),
    ("лавка", "Продукты"), ("vardanyan", "Продукты"),
    ("станем друзьями", "Продукты"), ("дикси", "Продукты"),
    ("вареничная", "Кафе"), ("rostics", "Кафе"),
    ("штопор", "Кафе"), ("хиросима", "Кафе"),
    ("добрый пекарь", "Кафе"), ("кафе", "Кафе"),
    ("ресторан", "Кафе"), ("суши", "Кафе"),
    ("газпром", "Авто"), ("азс", "Авто"),
    ("ампп", "Авто"), ("гибдд", "Авто"),
    ("платная дорога", "Авто"), ("автодор", "Авто"),
    ("lamoda", "Одежда"), ("ламода", "Одежда"),
    ("wildberries", "Одежда"), ("offprice", "Одежда"),
    ("мегафон", "Связь и подписки"), ("яндекс плюс", "Связь и подписки"),
    ("vk music", "Связь и подписки"), ("t-bundle", "Связь и подписки"),
    ("билайн", "Связь и подписки"), ("мтс", "Связь и подписки"),
    ("мосэнерго", "ЖКХ"), ("водоканал", "ЖКХ"),
    ("аптека", "Здоровье"), ("архимед", "Здоровье"),
    ("спортзал", "Спорт и уход"), ("barber", "Спорт и уход"),
    ("барбер", "Спорт и уход"),
    ("мфюа", "Образование"),
    ("firstbyte", "IT и серверы"), ("селектел", "IT и серверы"),
    ("selectel", "IT и серверы"), ("reg.ru", "IT и серверы"),
    ("cnt.ru", "IT и серверы"),
    ("мойчай", "Чай"), ("moychay", "Чай"), ("китайский чай", "Чай"),
    ("ozon", "Маркетплейсы"), ("озон", "Маркетплейсы"),
    ("avito", "Маркетплейсы"), ("авито", "Маркетплейсы"),
    ("яндекс го", "Транспорт"), ("такси", "Транспорт"),
    ("метро", "Транспорт"), ("аэроэкспресс", "Транспорт"),
]


async def ensure_seeded(db: AsyncSession, user_id: int) -> None:
    from db.finance_queries import count_categories
    from db.models import FinCategory, MerchantRule

    if await count_categories(db, user_id) > 0:
        return

    cat_map: dict[str, FinCategory] = {}

    for i, (icon, name) in enumerate(DEFAULT_EXPENSE_CATS):
        cat = FinCategory(
            user_id=user_id, name=name, icon=icon, cat_type="expense", sort_order=i
        )
        db.add(cat)
        cat_map[name] = cat

    for i, (icon, name) in enumerate(DEFAULT_INCOME_CATS):
        cat = FinCategory(
            user_id=user_id, name=name, icon=icon, cat_type="income", sort_order=100 + i
        )
        db.add(cat)
        cat_map[name] = cat

    await db.flush()

    for pattern, cat_name in DEFAULT_MERCHANT_RULES:
        cat = cat_map.get(cat_name)
        if cat:
            db.add(MerchantRule(
                user_id=user_id, pattern=pattern, category_id=cat.id
            ))

    await db.commit()
