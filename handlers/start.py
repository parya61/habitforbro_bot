"""Старт, помощь, навигация, общая отмена."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import create_user, get_user_by_tg
from keyboards.main_menu import MAIN_MENU
from keyboards.nav import home_kb, main_inline_kb

router = Router()

WELCOME = (
    "🌱 <b>Приветствую тебя!</b>\n\n"
    "Если ты оказался здесь — значит, ты хочешь измениться в лучшую сторону, "
    "и это радует. Большие перемены в жизни складываются из маленьких, но "
    "регулярных привычек.\n\n"
    "Не спеши сразу что-то добавлять. Представь, каким человеком ты себя видишь "
    "и хочешь быть по жизни. Подумай, что делает такой человек, какой образ жизни "
    "он ведёт — и только тогда добавляй привычки.\n\n"
    "Начни с малого, не нагружай себя сразу, добавляй постепенно. Главное в этом "
    "деле — <b>регулярность</b>.\n\n"
    "Я верю, что у тебя всё получится. 💪\n\n"
    "Всё управляется кнопками 👇"
)


async def send_menu(message: Message) -> None:
    """Показывает главное меню: нижнюю клавиатуру + inline-кнопки разделов."""
    await message.answer(WELCOME, reply_markup=MAIN_MENU)
    await message.answer("Главное меню:", reply_markup=main_inline_kb())

HELP_TEXT = (
    "ℹ️ <b>Помощь</b>\n\n"
    "<b>Команды:</b>\n"
    "/today — привычки на сегодня и отметки\n"
    "/habits — мои привычки (создать, изменить, архив)\n"
    "/goals — цели и планы\n"
    "/diary — личный дневник\n"
    "/stats — статистика и серии\n"
    "/leaderboard — рейтинг участников\n"
    "/start — главное меню\n\n"
    "<b>Обозначения:</b>\n"
    "🔥 — текущая серия (сколько дней подряд выполняешь)\n"
    "🏆 — лучшая серия за всё время (твой рекорд)\n"
    "✅ — привычка выполнена\n"
    "⬜ — привычка ещё не отмечена\n"
    "🔒 — приватная привычка (видишь только ты)\n\n"
    "<b>❄️ Заморозка:</b>\n"
    "Можно пропустить до 2 дней в месяц без потери серии. "
    "Заморозки расходуются автоматически. Если пропусков больше 2 — серия обнуляется.\n\n"
    "<b>⏰ Отметки:</b>\n"
    "Привычки за сегодня — до конца дня. "
    "Забыл отметить вчера? Раздел «📅 Вчера» доступен до 12:00.\n\n"
    "<b>🔐 Приватность:</b>\n"
    "Дневник по умолчанию приватный. Привычки можно сделать публичными "
    "(видят все участники) или скрытыми ото всех."
)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user
    user = await get_user_by_tg(session, tg.id)
    if user is None:
        user = await create_user(session, tg.id, tg.username, tg.full_name)
    await send_menu(message)


# Соответствие кнопок нижней клавиатуры разделам.
MENU_TEXTS = {
    "📋 Сегодня": "today",
    "📅 Вчера": "yesterday",
    "➕ Привычки": "habits",
    "🎯 Цели": "goals",
    "📔 Дневник": "diary",
    "📊 Статистика": "stats",
    "🏆 Рейтинг": "leaderboard",
    "👥 Участники": "members",
    "🎁 Призы": "prizes",
    "💰 Финансы": "finance",
    "⚙️ Настройки": "settings",
    "ℹ️ Помощь": "help",
}


async def _dispatch(dest: str, msg: Message, session: AsyncSession, user: User) -> None:
    """Открывает нужный раздел. Ленивая загрузка — против циклических импортов."""
    if dest == "menu":
        await msg.answer("Главное меню:", reply_markup=main_inline_kb())
    elif dest == "help":
        await msg.answer(HELP_TEXT, reply_markup=home_kb())
    elif dest == "today":
        from handlers.today import show_today
        await show_today(msg, session, user)
    elif dest == "yesterday":
        from handlers.yesterday import show_yesterday
        await show_yesterday(msg, session, user)
    elif dest == "habits":
        from handlers.habits import show_habits_list
        await show_habits_list(msg, session, user)
    elif dest == "goals":
        from handlers.goals import show_goals_menu
        await show_goals_menu(msg)
    elif dest == "diary":
        from handlers.diary import cmd_diary
        await cmd_diary(msg)
    elif dest == "stats":
        from handlers.stats import cmd_stats
        await cmd_stats(msg, session, user)
    elif dest == "leaderboard":
        from handlers.leaderboard import cmd_leaderboard
        await cmd_leaderboard(msg, session)
    elif dest == "members":
        from handlers.members import show_members
        await show_members(msg, session)
    elif dest == "prizes":
        from handlers.prizes import show_prizes
        await show_prizes(msg, session, user)
    elif dest == "finance":
        from handlers.finance import cmd_finance
        await cmd_finance(msg, session, user)
    elif dest == "tea":
        from handlers.tea import cmd_tea
        await cmd_tea(msg, user)
    elif dest == "settings":
        from handlers.settings import cmd_settings
        await cmd_settings(msg, user)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=home_kb())


@router.message(F.text.in_(MENU_TEXTS))
async def menu_text(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    """Нажатие кнопки нижнего меню в ЛЮБОМ состоянии: выходим из текущего
    сценария (чтобы не застрять в мастере) и открываем раздел."""
    await state.clear()
    await _dispatch(MENU_TEXTS[message.text], message, session, user)


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    from utils import safe_edit_text

    await safe_edit_text(callback.message, "Отменено.")
    await callback.message.answer("Главное меню:", reply_markup=main_inline_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("go:"))
async def navigate(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    """Единая навигация по разделам через inline-кнопки (без команд)."""
    await state.clear()
    dest = callback.data.split(":")[1]
    await _dispatch(dest, callback.message, session, user)
    await callback.answer()
