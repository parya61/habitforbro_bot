"""Автоматические миграции для добавления новых колонок в существующую БД."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


_COLUMN_MIGRATIONS = [
    ("habits", "description", "ALTER TABLE habits ADD COLUMN description TEXT"),
    ("users", "nickname", "ALTER TABLE users ADD COLUMN nickname VARCHAR(64)"),
    ("users", "tea_diary_private", "ALTER TABLE users ADD COLUMN tea_diary_private BOOLEAN DEFAULT 0"),
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
