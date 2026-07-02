"""Автоматические миграции для добавления новых колонок в существующую БД."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


_COLUMN_MIGRATIONS = [
    ("habits", "description", "ALTER TABLE habits ADD COLUMN description TEXT"),
    ("users", "nickname", "ALTER TABLE users ADD COLUMN nickname VARCHAR(64)"),
    ("users", "tea_diary_private", "ALTER TABLE users ADD COLUMN tea_diary_private BOOLEAN DEFAULT 0"),
    ("prizes", "winner_2_user_id", "ALTER TABLE prizes ADD COLUMN winner_2_user_id INTEGER REFERENCES users(id)"),
    ("prizes", "winner_3_user_id", "ALTER TABLE prizes ADD COLUMN winner_3_user_id INTEGER REFERENCES users(id)"),
    ("tea_sessions", "brew_temp", "ALTER TABLE tea_sessions ADD COLUMN brew_temp INTEGER"),
    ("tea_sessions", "brew_time", "ALTER TABLE tea_sessions ADD COLUMN brew_time VARCHAR(32)"),
    ("tea_sessions", "infusions", "ALTER TABLE tea_sessions ADD COLUMN infusions INTEGER"),
    ("tea_sessions", "teaware", "ALTER TABLE tea_sessions ADD COLUMN teaware VARCHAR(64)"),
    ("tea_sessions", "ratio", "ALTER TABLE tea_sessions ADD COLUMN ratio VARCHAR(32)"),
    ("tea_sessions", "brew_time_seconds", "ALTER TABLE tea_sessions ADD COLUMN brew_time_seconds INTEGER"),
    ("tea_sessions", "teaware_item_id", "ALTER TABLE tea_sessions ADD COLUMN teaware_item_id INTEGER"),
    ("tea_sessions", "tea_grams", "ALTER TABLE tea_sessions ADD COLUMN tea_grams REAL"),
    ("tea_sessions", "water_ml", "ALTER TABLE tea_sessions ADD COLUMN water_ml INTEGER"),
    ("tea_sessions", "brewing_method", "ALTER TABLE tea_sessions ADD COLUMN brewing_method VARCHAR(32)"),
]


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, column, sql in _COLUMN_MIGRATIONS:
            exists = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM pragma_table_info(:tbl) WHERE name = :col"
                ),
                {"tbl": table, "col": column},
            )
            if not exists:
                await conn.execute(text(sql))
