"""Сбор всех роутеров бота в один список для регистрации в диспетчере."""
from aiogram import Router

from handlers import (
    admin,
    analytics,
    cafe,
    diary,
    fallback,
    finance,
    goals,
    grocery,
    habits,
    leaderboard,
    members,
    prizes,
    settings,
    start,
    stats,
    today,
    yesterday,
)


def get_routers() -> list[Router]:
    # Порядок важен: старт/навигация сначала, фоллбэк — обязательно последним.
    return [
        start.router,
        admin.router,
        habits.router,
        today.router,
        yesterday.router,
        diary.router,
        goals.router,
        stats.router,
        leaderboard.router,
        members.router,
        prizes.router,
        analytics.router,
        finance.router,
        grocery.router,
        cafe.router,
        settings.router,
        fallback.router,
    ]
