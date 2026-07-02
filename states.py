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
    custom_type = State()  # ввод своего вида чая
    tastes = State()       # вкусовые предпочтения
    custom_taste = State() # ввод своего вкусового тега


class TeaSessionFlow(StatesGroup):
    name = State()         # название чая
    tea_type = State()     # вид чая
    custom_type = State()  # ввод своего вида чая
    temp = State()         # температура воды
    custom_temp = State()  # ввод своей температуры
    brew_time = State()    # время заваривания
    infusions = State()    # количество проливов
    teaware = State()      # посуда
    brewing_method = State()  # метод заваривания
    ratio = State()        # пропорция г/мл
    rating = State()       # оценка 1-10
    tags = State()         # вкусовые теги (мультивыбор)
    custom_tag = State()   # ввод своего вкусового тега
    notes = State()        # заметки (аромат, вкус, заваривание)
    photo = State()        # фото
    qi = State()           # ча ци


class TeaEditFlow(StatesGroup):
    name = State()         # новое название чая
    notes = State()        # новые заметки
    photo = State()        # добавить фото


class TeaCollectionFlow(StatesGroup):
    name = State()         # название чая
    tea_type = State()     # вид чая
    custom_type = State()  # свой вид чая
    weight = State()       # вес в граммах
    price = State()        # цена
    vendor = State()       # продавец/магазин
    year = State()         # год сбора
    notes = State()        # заметки


class TeaCollEditFlow(StatesGroup):
    name = State()         # новое название
    weight = State()       # новый вес
    price = State()        # новая цена
    vendor = State()       # новый продавец
    notes = State()        # новые заметки
    subtract = State()     # списать граммы


class TeawareFlow(StatesGroup):
    name = State()         # название посуды
    teaware_type = State() # тип (гайвань, исинский и т.д.)
    material = State()     # материал
    volume = State()       # объём в мл
    notes = State()        # заметки


class TeawareEditFlow(StatesGroup):
    name = State()         # новое название
    volume = State()       # новый объём
    notes = State()        # новые заметки


class TeaMessageFlow(StatesGroup):
    text = State()         # текст сообщения о чае
