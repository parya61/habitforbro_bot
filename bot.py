"""Точка входа: запуск бота в режиме long polling."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from config import config
from db.database import init_db
from handlers import get_routers
from middlewares.auth import AuthMiddleware
from services.scheduler import setup_scheduler

# Команды для синего меню «/» в Telegram.
BOT_COMMANDS = [
    BotCommand(command="start", description="🏠 Главное меню"),
    BotCommand(command="today", description="📋 Привычки на сегодня"),
    BotCommand(command="yesterday", description="📅 Отметить за вчера (до 12:00)"),
    BotCommand(command="habits", description="➕ Мои привычки"),
    BotCommand(command="goals", description="🎯 Цели"),
    BotCommand(command="diary", description="📔 Дневник"),
    BotCommand(command="stats", description="📊 Статистика"),
    BotCommand(command="leaderboard", description="🏆 Рейтинг"),
    BotCommand(command="help", description="ℹ️ Помощь"),
]


async def on_error(event: ErrorEvent) -> None:
    """Глобальный перехват ошибок: логируем и мягко уведомляем пользователя,
    чтобы бот не «зависал» молча и продолжал работать."""
    logger.exception("Ошибка при обработке обновления: %s", event.exception)
    update = event.update
    text = "⚠️ Упс, что-то пошло не так. Попробуй ещё раз или нажми /start."
    try:
        if update.message:
            await update.message.answer(text)
        elif update.callback_query:
            await update.callback_query.answer(
                "Что-то пошло не так, попробуй ещё раз", show_alert=True
            )
    except Exception:
        pass

# Логи пишем в файл с явным UTF-8 (не зависим от кодовой страницы консоли Windows)
# и дублируем в stdout для запуска вручную.
_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("habits-bot")


async def main() -> None:
    await init_db()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Контроль доступа + сессия БД для всех сообщений и колбэков.
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    for router in get_routers():
        dp.include_router(router)

    # Глобальный перехватчик ошибок.
    dp.errors.register(on_error)

    await setup_scheduler(bot)

    await bot.set_my_commands(BOT_COMMANDS)

    logger.info("Бот запущен. Ожидаю сообщения…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
