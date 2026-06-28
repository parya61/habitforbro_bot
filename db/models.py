"""Модели базы данных (SQLAlchemy 2.x, async-стиль).

Ключевое расширение под нашу задачу — у привычки есть приватность:
- 'public'  — привычку видят все участники группы (по умолчанию);
- 'private' — привычка скрыта ото всех, её видит только сам автор.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")

    # Приватность дневника по умолчанию: True — записи видит только автор.
    diary_private: Mapped[bool] = mapped_column(Boolean, default=True)
    # Флаг доступа: разрешён ли вход (прошёл проверку кодового слова/whitelist).
    has_access: Mapped[bool] = mapped_column(Boolean, default=False)

    # Настройки рассылок.
    morning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evening_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    habits: Mapped[list["Habit"]] = relationship(back_populates="user")
    diary_entries: Mapped[list["DiaryEntry"]] = relationship(back_populates="user")
    achievements: Mapped[list["Achievement"]] = relationship(back_populates="user")


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    emoji: Mapped[str] = mapped_column(String(16), default="✅")

    # Тип: 'binary' — да/нет, 'quantitative' — с количеством.
    type: Mapped[str] = mapped_column(String(16), default="binary")
    target: Mapped[int | None] = mapped_column(Integer, nullable=True)  # цель в день
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)  # раз/минут/...

    remind_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # 'HH:MM'
    place: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Периодичность: 'daily' | 'weekdays' | 'times_per_week'.
    frequency: Mapped[str] = mapped_column(String(16), default="daily")
    # Для 'weekdays' — строка дней недели '0,1,2' (пн=0). Для 'times_per_week' — число.
    freq_value: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Приватность привычки: 'public' (видят все) | 'private' (скрыта ото всех).
    privacy: Mapped[str] = mapped_column(String(16), default="public")

    # Статус: 'active' | 'archived'.
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="habits")
    logs: Mapped[list["HabitLog"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )

    @property
    def is_private(self) -> bool:
        return self.privacy == "private"


class HabitLog(Base):
    __tablename__ = "habit_logs"
    __table_args__ = (UniqueConstraint("habit_id", "log_date", name="uq_habit_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), index=True
    )
    log_date: Mapped[date] = mapped_column(Date, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # факт. кол-во
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    marked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    habit: Mapped["Habit"] = relationship(back_populates="logs")


class DiaryEntry(Base):
    __tablename__ = "diary_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(Text)
    mood: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Приватность записи: True — видит только автор.
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="diary_entries")


class Achievement(Base):
    __tablename__ = "achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "code", "habit_id", name="uq_user_achievement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Код достижения, например 'streak_7', 'all_done', 'early_bird'.
    code: Mapped[str] = mapped_column(String(32))
    # К какой привычке относится (для streak-бейджей). Может быть None.
    habit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    earned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="achievements")


class Prize(Base):
    __tablename__ = "prizes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), unique=True, index=True)  # "YYYY-MM"
    description: Mapped[str] = mapped_column(Text)
    prize_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    winner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    announced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    winner: Mapped["User | None"] = relationship()
