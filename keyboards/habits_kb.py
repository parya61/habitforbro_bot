"""Клавиатуры мастера создания и управления привычками."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Готовые шаблоны привычек: (эмодзи, название).
TEMPLATES: list[tuple[str, str]] = [
    ("💪", "Отжимания"),
    ("🏃", "Зарядка"),
    ("📖", "Чтение"),
    ("🧘", "Медитация"),
    ("💧", "Пить воду"),
    ("🚶", "Прогулка"),
    ("😴", "Лечь спать вовремя"),
    ("📔", "Вести дневник"),
    ("🚭", "Отказ от вредной привычки"),
]

# Дни недели для выбора периодичности (пн=0).
WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def start_create_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Из шаблонов", callback_data="new:templates")
    kb.button(text="✏️ Своя привычка", callback_data="new:custom")
    kb.adjust(1)
    return kb.as_markup()


def templates_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for idx, (emoji, name) in enumerate(TEMPLATES):
        kb.button(text=f"{emoji} {name}", callback_data=f"tpl:{idx}")
    kb.button(text="✖️ Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def type_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Просто отметка", callback_data="type:binary")
    kb.button(text="🔢 С количеством", callback_data="type:quantitative")
    kb.adjust(1)
    return kb.as_markup()


def unit_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for unit in ("раз", "минут", "страниц", "стаканов", "км"):
        kb.button(text=unit, callback_data=f"unit:{unit}")
    kb.adjust(3)
    return kb.as_markup()


def frequency_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Каждый день", callback_data="freq:daily")
    kb.button(text="🗓 По дням недели", callback_data="freq:weekdays")
    kb.button(text="🔁 N раз в неделю", callback_data="freq:times_per_week")
    kb.adjust(1)
    return kb.as_markup()


def weekdays_kb(selected: set[int]) -> InlineKeyboardMarkup:
    """Клавиатура выбора дней недели с галочками выбранных."""
    kb = InlineKeyboardBuilder()
    for idx, name in enumerate(WEEKDAY_NAMES):
        mark = "✅" if idx in selected else "▫️"
        kb.button(text=f"{mark} {name}", callback_data=f"wd:{idx}")
    kb.button(text="Готово ▶️", callback_data="wd:done")
    kb.adjust(4, 3, 1)
    return kb.as_markup()


def times_per_week_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in range(1, 8):
        kb.button(text=str(n), callback_data=f"tpw:{n}")
    kb.adjust(7)
    return kb.as_markup()


def privacy_kb() -> InlineKeyboardMarkup:
    """Шаг выбора приватности привычки при создании."""
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Видят все участники", callback_data="priv:public")
    kb.button(text="🔒 Скрыть ото всех", callback_data="priv:private")
    kb.adjust(1)
    return kb.as_markup()


def reminder_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏰ Указать время", callback_data="rem:set")
    kb.button(text="➡️ Без напоминания", callback_data="rem:skip")
    kb.adjust(1)
    return kb.as_markup()


def place_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Указать место", callback_data="place:set")
    kb.button(text="✅ Завершить", callback_data="place:skip")
    kb.adjust(1)
    return kb.as_markup()


def habit_actions_kb(habit_id: int, privacy: str) -> InlineKeyboardMarkup:
    """Меню действий с конкретной привычкой."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Трекер", callback_data=f"hb:tracker:{habit_id}")
    if privacy == "public":
        kb.button(text="🔒 Скрыть ото всех", callback_data=f"hb:priv:{habit_id}:private")
    else:
        kb.button(text="👥 Открыть всем", callback_data=f"hb:priv:{habit_id}:public")
    kb.button(text="✏️ Изменить", callback_data=f"hb:edit:{habit_id}")
    kb.button(text="🗄 В архив", callback_data=f"hb:archive:{habit_id}")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def habit_edit_kb(habit) -> InlineKeyboardMarkup:
    """Меню редактирования параметров привычки."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Название", callback_data=f"hb:rename:{habit.id}")
    if habit.type == "quantitative":
        kb.button(text="🎯 Цель", callback_data=f"he:target:{habit.id}")
    kb.button(text="🔁 Периодичность", callback_data=f"he:freq:{habit.id}")
    rem = "⏰ Напоминание" if not habit.remind_time else f"⏰ Напоминание ({habit.remind_time})"
    kb.button(text=rem, callback_data=f"he:rem:{habit.id}")
    kb.button(text="⬅️ Назад", callback_data=f"hb:open:{habit.id}")
    kb.adjust(1)
    return kb.as_markup()


def edit_frequency_kb(habit_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Каждый день", callback_data=f"hef:{habit_id}:daily")
    kb.button(text="🗓 По дням недели", callback_data=f"hef:{habit_id}:weekdays")
    kb.button(text="🔁 N раз в неделю", callback_data=f"hef:{habit_id}:times_per_week")
    kb.adjust(1)
    return kb.as_markup()


def edit_weekdays_kb(selected: set[int]) -> InlineKeyboardMarkup:
    """Выбор дней недели при редактировании (отдельный префикс от мастера)."""
    kb = InlineKeyboardBuilder()
    for idx, name in enumerate(WEEKDAY_NAMES):
        mark = "✅" if idx in selected else "▫️"
        kb.button(text=f"{mark} {name}", callback_data=f"hewd:{idx}")
    kb.button(text="Готово ▶️", callback_data="hewd:done")
    kb.adjust(4, 3, 1)
    return kb.as_markup()


def edit_times_per_week_kb(habit_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in range(1, 8):
        kb.button(text=str(n), callback_data=f"hetpw:{habit_id}:{n}")
    kb.adjust(7)
    return kb.as_markup()


def habits_list_kb(habits) -> InlineKeyboardMarkup:
    """Список привычек кнопками + добавить новую."""
    kb = InlineKeyboardBuilder()
    for habit in habits:
        lock = " 🔒" if habit.privacy == "private" else ""
        kb.button(
            text=f"{habit.emoji} {habit.title}{lock}",
            callback_data=f"hb:open:{habit.id}",
        )
    kb.button(text="➕ Новая привычка", callback_data="new:start")
    kb.button(text="🗄 Архив", callback_data="hb:arclist")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(1)
    return kb.as_markup()


def archived_list_kb(habits) -> InlineKeyboardMarkup:
    """Список архивированных привычек: нажатие восстанавливает привычку."""
    kb = InlineKeyboardBuilder()
    for habit in habits:
        kb.button(
            text=f"♻️ {habit.emoji} {habit.title}",
            callback_data=f"hb:restore:{habit.id}",
        )
    kb.button(text="⬅️ К привычкам", callback_data="go:habits")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(1)
    return kb.as_markup()
