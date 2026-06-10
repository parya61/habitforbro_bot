"""Сбор всех роутеров бота в один список для регистрации в диспетчере."""
from aiogram import Router

from handlers import (
    diary,
    fallback,
    habits,
    leaderboard,
    members,
    settings,
    start,
    stats,
    today,
)


def get_routers() -> list[Router]:
    # Порядок важен: старт/навигация сначала, фоллбэк — обязательно последним.
    return [
        start.router,
        habits.router,
        today.router,
        diary.router,
        stats.router,
        leaderboard.router,
        members.router,
        settings.router,
        fallback.router,
    ]
