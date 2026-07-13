"""Сбор всех роутеров бота в один список для регистрации в диспетчере."""
from aiogram import Router

from handlers import (
    admin,
    diary,
    fallback,
    goals,
    habits,
    leaderboard,
    members,
    prizes,
    settings,
    start,
    stats,
    today,
)


def get_routers() -> list[Router]:
    # Порядок важен: старт/навигация сначала, фоллбэк — обязательно последним.
    return [
        start.router,
        admin.router,
        habits.router,
        today.router,
        diary.router,
        goals.router,
        stats.router,
        leaderboard.router,
        members.router,
        prizes.router,
        settings.router,
        fallback.router,
    ]
