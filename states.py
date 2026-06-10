"""FSM-состояния для пошаговых сценариев."""
from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    code = State()  # ввод кодового слова при первом /start


class CreateHabit(StatesGroup):
    title = State()        # ввод названия (для своей привычки)
    target = State()       # цель (для количественной)
    weekdays = State()     # выбор дней недели
    reminder = State()     # ввод времени напоминания
    place = State()        # ввод места


class LogQuantity(StatesGroup):
    amount = State()       # ввод фактического количества
    note = State()         # заметка к отметке


class DiaryFlow(StatesGroup):
    text = State()         # текст записи дневника


class RenameHabit(StatesGroup):
    title = State()        # новое название привычки


class EditHabit(StatesGroup):
    reminder = State()     # новое время напоминания (или отключение)
    target = State()       # новая дневная цель (для количественной)


class SettingsFlow(StatesGroup):
    timezone = State()     # ввод часового пояса
