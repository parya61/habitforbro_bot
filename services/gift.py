"""Gift module: holidays, relationships, formatting."""
from __future__ import annotations

from datetime import date

RELATIONSHIPS = [
    ("wife", "👩 Жена"),
    ("mom", "👩‍🦳 Мама"),
    ("dad", "👨‍🦳 Папа"),
    ("sister", "👧 Сестра"),
    ("brother", "👦 Брат"),
    ("friend_m", "🧑 Друг"),
    ("friend_f", "👩 Подруга"),
    ("colleague", "💼 Коллега"),
    ("other", "👤 Другое"),
]

REL_LABELS = dict(RELATIONSHIPS)

HOLIDAYS = [
    (12, 31, "🎄 Новый год"),
    (3, 8, "🌷 8 Марта"),
    (2, 23, "🎖 23 Февраля"),
    (2, 14, "💕 День святого Валентина"),
]

GIFT_STATUSES = {
    "idea": "💡 Идея",
    "bought": "🛍 Куплено",
    "given": "🎁 Подарено",
}

ALERT_DAYS = 21


def upcoming_birthdays(persons: list, ref_date: date, days_ahead: int = 30) -> list[tuple]:
    results = []
    for p in persons:
        if not p.birthday:
            continue
        this_year = p.birthday.replace(year=ref_date.year)
        if this_year < ref_date:
            this_year = this_year.replace(year=ref_date.year + 1)
        delta = (this_year - ref_date).days
        if 0 <= delta <= days_ahead:
            age = this_year.year - p.birthday.year
            results.append((p, this_year, delta, age))
    results.sort(key=lambda x: x[2])
    return results


def upcoming_holidays(ref_date: date, days_ahead: int = 30) -> list[tuple[date, str, int]]:
    results = []
    for month, day, name in HOLIDAYS:
        this_year = date(ref_date.year, month, day)
        if this_year < ref_date:
            this_year = this_year.replace(year=ref_date.year + 1)
        delta = (this_year - ref_date).days
        if 0 <= delta <= days_ahead:
            results.append((this_year, name, delta))
    results.sort(key=lambda x: x[2])
    return results


def days_label(days: int) -> str:
    if days == 0:
        return "сегодня!"
    if days == 1:
        return "завтра"
    if days < 5:
        return f"через {days} дня"
    return f"через {days} дней"
