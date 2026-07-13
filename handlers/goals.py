"""Цели: постановка и отслеживание целей разного масштаба."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    achieve_goal,
    create_goal,
    delete_goal,
    get_goal,
    list_achieved_goals,
    list_goals,
    update_goal_title,
)
from keyboards.nav import home_kb
from states import GoalFlow
from utils import esc

router = Router()

LEVELS = {
    "life": "🌟 На жизнь",
    "year": "📅 На год",
    "month": "🗓 На месяц",
    "tomorrow": "⏰ На завтра",
}

LEVEL_TITLES = {
    "life": "🌟 Цели на жизнь",
    "year": "📅 Цели на год",
    "month": "🗓 Цели на месяц",
    "tomorrow": "⏰ Цели на завтра",
}

LEVEL_PROMPTS = {
    "life": "🌟 Напиши свою глобальную цель:",
    "year": "📅 Какую цель ставишь на этот год?",
    "month": "🗓 Что хочешь достичь в этом месяце?",
    "tomorrow": "⏰ Что планируешь на завтра?",
}

MENU_TEXT = (
    "🎯 <b>Цели</b>\n\n"
    "Ставь цели разного масштаба — от глобальных мечт до планов на завтра."
)


def _goals_menu_kb():
    kb = InlineKeyboardBuilder()
    for key, label in LEVELS.items():
        kb.button(text=label, callback_data=f"goals:level:{key}")
    kb.button(text="📦 Архив достижений", callback_data="goals:archive")
    kb.adjust(2, 2, 1)
    return kb


def _level_kb(level: str, goals):
    kb = InlineKeyboardBuilder()
    for g in goals:
        short = g.title[:32] + ("…" if len(g.title) > 32 else "")
        kb.button(text=short, callback_data=f"goals:view:{g.id}")
    kb.adjust(1)
    bottom = InlineKeyboardBuilder()
    bottom.button(text="➕ Добавить", callback_data=f"goals:add:{level}")
    bottom.button(text="⬅️ Назад", callback_data="goals:menu")
    bottom.adjust(2)
    kb.attach(bottom)
    return kb


def _goal_detail_kb(goal):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить", callback_data=f"goals:edit:{goal.id}")
    kb.button(text="✅ Достигнута!", callback_data=f"goals:ach:{goal.id}")
    kb.button(text="🗑 Удалить", callback_data=f"goals:del:{goal.id}")
    kb.button(text="⬅️ Назад", callback_data=f"goals:level:{goal.level}")
    kb.adjust(2, 1, 1)
    return kb


def _back_to_level_kb(level: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⬅️ {LEVELS[level]}", callback_data=f"goals:level:{level}")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


# ---- Entry points ----


async def show_goals_menu(message: Message) -> None:
    await message.answer(MENU_TEXT, reply_markup=_goals_menu_kb().as_markup())


@router.message(Command("goals"))
@router.message(F.text == "🎯 Цели")
async def cmd_goals(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_goals_menu(message)


@router.callback_query(F.data == "goals:menu")
async def goals_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        MENU_TEXT, reply_markup=_goals_menu_kb().as_markup()
    )
    await callback.answer()


# ---- Level view ----

@router.callback_query(F.data.startswith("goals:level:"))
async def goals_by_level(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    level = callback.data.split(":")[2]
    if level not in LEVELS:
        await callback.answer("Неизвестный уровень", show_alert=True)
        return

    goals = await list_goals(session, user.id, level)
    title = LEVEL_TITLES[level]

    if not goals:
        text = f"{title}\n\nПока нет целей. Добавь первую!"
    else:
        lines = [f"{title}\n"]
        for i, g in enumerate(goals, 1):
            date_str = g.created_at.strftime("%d.%m.%Y")
            edited = ""
            if g.updated_at and g.updated_at > g.created_at:
                if (g.updated_at - g.created_at).total_seconds() > 60:
                    edited = f" · изм. {g.updated_at.strftime('%d.%m.%Y')}"
            lines.append(f"{i}. {esc(g.title)} <i>({date_str}{edited})</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text, reply_markup=_level_kb(level, goals).as_markup()
    )
    await callback.answer()


# ---- Goal detail ----

@router.callback_query(F.data.startswith("goals:view:"))
async def goal_detail(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    goal_id = int(callback.data.split(":")[2])
    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await callback.answer("Цель не найдена", show_alert=True)
        return

    level_label = LEVELS.get(goal.level, "")
    date_str = goal.created_at.strftime("%d.%m.%Y")
    lines = [
        f"{level_label}\n",
        f"<b>{esc(goal.title)}</b>\n",
        f"📌 Добавлено: {date_str}",
    ]
    if goal.updated_at and (goal.updated_at - goal.created_at).total_seconds() > 60:
        lines.append(f"✏️ Изменено: {goal.updated_at.strftime('%d.%m.%Y')}")

    await callback.message.edit_text(
        "\n".join(lines), reply_markup=_goal_detail_kb(goal).as_markup()
    )
    await callback.answer()


# ---- Add goal ----

@router.callback_query(F.data.startswith("goals:add:"))
async def goal_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":")[2]
    if level not in LEVELS:
        await callback.answer("Ошибка", show_alert=True)
        return
    await state.set_state(GoalFlow.title)
    await state.update_data(goal_level=level)

    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="goals:menu")
    await callback.message.answer(
        LEVEL_PROMPTS[level], reply_markup=kb.as_markup()
    )
    await callback.answer()


@router.message(GoalFlow.title)
async def goal_add_save(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Пустую цель не сохраню. Напиши что-нибудь:")
        return
    if len(title) > 500:
        await message.answer("Слишком длинный текст (макс. 500). Сократи:")
        return
    data = await state.get_data()
    level = data.get("goal_level", "life")
    await state.clear()
    goal = await create_goal(session, user.id, level, title)

    await message.answer(
        f"✅ Цель добавлена!\n\n<b>{esc(goal.title)}</b>",
        reply_markup=_back_to_level_kb(level).as_markup(),
    )


# ---- Edit goal ----

@router.callback_query(F.data.startswith("goals:edit:"))
async def goal_edit_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    goal_id = int(callback.data.split(":")[2])
    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await callback.answer("Цель не найдена", show_alert=True)
        return

    await state.set_state(GoalFlow.edit)
    await state.update_data(goal_edit_id=goal_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data=f"goals:view:{goal_id}")
    await callback.message.answer(
        f"Текущий текст:\n<b>{esc(goal.title)}</b>\n\nВведи новый текст:",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(GoalFlow.edit)
async def goal_edit_save(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Пустую цель не сохраню. Напиши что-нибудь:")
        return
    if len(title) > 500:
        await message.answer("Слишком длинный текст (макс. 500). Сократи:")
        return
    data = await state.get_data()
    goal_id = data.get("goal_edit_id")
    await state.clear()

    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await message.answer("Цель не найдена.")
        return

    await update_goal_title(session, goal, title)

    await message.answer(
        f"✅ Цель обновлена!\n\n<b>{esc(title)}</b>",
        reply_markup=_back_to_level_kb(goal.level).as_markup(),
    )


# ---- Achieve goal ----

@router.callback_query(F.data.startswith("goals:ach:"))
async def goal_achieve_cb(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    goal_id = int(callback.data.split(":")[2])
    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await callback.answer("Цель не найдена", show_alert=True)
        return

    level = goal.level
    await achieve_goal(session, goal)

    kb = InlineKeyboardBuilder()
    kb.button(text=f"⬅️ {LEVELS[level]}", callback_data=f"goals:level:{level}")
    kb.button(text="📦 Архив", callback_data="goals:archive")
    kb.adjust(2)

    await callback.message.edit_text(
        f"🎉 Поздравляю! Цель достигнута!\n\n✅ <b>{esc(goal.title)}</b>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# ---- Delete goal ----

@router.callback_query(F.data.startswith("goals:del:"))
async def goal_delete_confirm(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    goal_id = int(callback.data.split(":")[2])
    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await callback.answer("Цель не найдена", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=f"goals:rm:{goal_id}")
    kb.button(text="Отмена", callback_data=f"goals:view:{goal_id}")
    kb.adjust(2)

    await callback.message.edit_text(
        f"🗑 Удалить цель?\n\n<b>{esc(goal.title)}</b>",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("goals:rm:"))
async def goal_delete_execute(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    goal_id = int(callback.data.split(":")[2])
    goal = await get_goal(session, goal_id)
    if goal is None or goal.user_id != user.id:
        await callback.answer("Цель не найдена", show_alert=True)
        return

    level = goal.level
    await delete_goal(session, goal)

    kb = InlineKeyboardBuilder()
    kb.button(text=f"⬅️ {LEVELS[level]}", callback_data=f"goals:level:{level}")

    await callback.message.edit_text("🗑 Цель удалена.", reply_markup=kb.as_markup())
    await callback.answer()


# ---- Archive ----

@router.callback_query(F.data == "goals:archive")
async def goals_archive(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    achieved = await list_achieved_goals(session, user.id)

    kb = InlineKeyboardBuilder()

    if not achieved:
        text = "📦 <b>Архив достижений</b>\n\nПока пусто — но всё впереди!"
    else:
        lines = ["📦 <b>Архив достижений</b>\n"]
        for g in achieved:
            emoji = LEVELS.get(g.level, "•").split()[0]
            date_str = g.achieved_at.strftime("%d.%m.%Y") if g.achieved_at else "—"
            lines.append(f"✅ {emoji} {esc(g.title)} <i>({date_str})</i>")
        text = "\n".join(lines)

    kb.button(text="⬅️ Назад", callback_data="goals:menu")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()
