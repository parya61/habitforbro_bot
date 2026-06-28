"""FSM-состояния для пошаговых сценариев."""
from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    code = State()  # ввод кодового слова при первом /start


class CreateHabit(StatesGroup):
    title = State()        # ввод названия (для своей привычки)
    target = State()       # цель (для количественной)
    weekdays = State()     # выбор дней недели
    description = State()  # описание привычки (опционально)
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
    description = State()  # новое описание привычки


class SettingsFlow(StatesGroup):
    timezone = State()     # ввод часового пояса
    nickname = State()     # ввод никнейма


class SendMessage(StatesGroup):
    text = State()         # текст сообщения участнику


class AdminPrize(StatesGroup):
    description = State()  # описание приза
    code = State()         # код/ссылка приза


class TeaProfileFlow(StatesGroup):
    story = State()        # "Мой путь к чаю"
    types = State()        # любимые виды чая
    tastes = State()       # вкусовые предпочтения


class TeaSessionFlow(StatesGroup):
    name = State()         # название чая
    tea_type = State()     # вид чая
    rating = State()       # оценка 1-10
    tags = State()         # вкусовые теги (мультивыбор)
    notes = State()        # заметки (аромат, вкус, заваривание)
    photo = State()        # фото
    qi = State()           # ча ци
