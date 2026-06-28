"""Создание, просмотр, редактирование и архивирование привычек.

Мастер создания включает отдельный шаг выбора приватности:
привычку можно сделать публичной (видят все участники) или скрыть ото всех.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    archive_habit,
    create_habit,
    get_habit,
    list_archived_habits,
    list_habits,
    restore_habit,
    update_habit,
)
from keyboards.nav import home_kb
from keyboards.habits_kb import (
    TEMPLATES,
    WEEKDAY_NAMES,
    archived_list_kb,
    description_kb,
    edit_frequency_kb,
    edit_times_per_week_kb,
    edit_weekdays_kb,
    frequency_kb,
    habit_actions_kb,
    habit_edit_kb,
    habits_list_kb,
    privacy_kb,
    place_kb,
    reminder_kb,
    start_create_kb,
    templates_kb,
    times_per_week_kb,
    type_kb,
    unit_kb,
    weekdays_kb,
)
from services.stats import render_tracker
from states import CreateHabit, EditHabit, RenameHabit
from utils import esc, safe_edit_text

router = Router()

PRIVACY_LABEL = {"public": "👥 видят все", "private": "🔒 скрыта ото всех"}

# Сообщение, когда мастер «протух» (нажата кнопка из старого сообщения).
STALE_WIZARD = "Мастер устарел 🙃 Начни заново через «➕ Привычки»."


async def _wizard_habit(callback: CallbackQuery, state: FSMContext) -> dict | None:
    """Достаёт данные мастера; если их нет (старая кнопка) — мягко прерывает."""
    data = await state.get_data()
    habit = data.get("habit")
    if habit is None:
        await callback.answer(STALE_WIZARD, show_alert=True)
    return habit


# ---------- Список привычек ----------

async def show_habits_list(message: Message, session: AsyncSession, user: User) -> None:
    habits = await list_habits(session, user.id)
    if not habits:
        text = "У тебя пока нет привычек. Добавь первую! 👇"
    else:
        lines = ["📋 <b>Твои привычки:</b>"]
        for h in habits:
            tag = " 🔒" if h.is_private else ""
            lines.append(f"{h.emoji} {esc(h.title)}{tag}")
        text = "\n".join(lines)
    await message.answer(text, reply_markup=habits_list_kb(habits))


@router.message(Command("habits"))
@router.message(F.text == "➕ Привычки")
async def cmd_habits(message: Message, session: AsyncSession, user: User) -> None:
    await show_habits_list(message, session, user)


# ---------- Мастер создания ----------

@router.callback_query(F.data == "new:start")
async def new_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "Как создадим привычку?", reply_markup=start_create_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "new:templates")
async def new_templates(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Выбери шаблон:", reply_markup=templates_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "new:custom")
async def new_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateHabit.title)
    await state.update_data(habit={"emoji": "✅"})
    await callback.message.answer("Введи название привычки:")
    await callback.answer()


@router.callback_query(F.data.startswith("tpl:"))
async def pick_template(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":")[1])
    emoji, name = TEMPLATES[idx]
    await state.update_data(habit={"emoji": emoji, "title": name})
    await callback.message.edit_text(
        f"{emoji} <b>{name}</b>\nКакой тип привычки?", reply_markup=type_kb()
    )
    await callback.answer()


@router.message(CreateHabit.title)
async def enter_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = data.get("habit", {"emoji": "✅"})
    habit["title"] = title[:128]
    await state.update_data(habit=habit)
    await state.set_state(None)
    await message.answer("Какой тип привычки?", reply_markup=type_kb())


@router.callback_query(F.data.startswith("type:"))
async def pick_type(callback: CallbackQuery, state: FSMContext) -> None:
    htype = callback.data.split(":")[1]
    habit = await _wizard_habit(callback, state)
    if habit is None:
        return
    habit["type"] = htype
    await state.update_data(habit=habit)

    if htype == "quantitative":
        await state.set_state(CreateHabit.target)
        await callback.message.answer(
            "Какая цель в день? Введи число (например, 50):"
        )
    else:
        await callback.message.answer(
            "Как часто выполнять?", reply_markup=frequency_kb()
        )
    await callback.answer()


@router.message(CreateHabit.target)
async def enter_target(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Нужно положительное число. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = data.get("habit")
    if habit is None:
        await message.answer(STALE_WIZARD)
        return
    habit["target"] = int(raw)
    await state.update_data(habit=habit)
    await state.set_state(None)
    await message.answer("Единица измерения:", reply_markup=unit_kb())


@router.callback_query(F.data.startswith("unit:"))
async def pick_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit = callback.data.split(":", 1)[1]
    habit = await _wizard_habit(callback, state)
    if habit is None:
        return
    habit["unit"] = unit
    await state.update_data(habit=habit)
    await callback.message.answer("Как часто выполнять?", reply_markup=frequency_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("freq:"))
async def pick_frequency(callback: CallbackQuery, state: FSMContext) -> None:
    freq = callback.data.split(":")[1]
    habit = await _wizard_habit(callback, state)
    if habit is None:
        return
    habit["frequency"] = freq
    await state.update_data(habit=habit)

    if freq == "weekdays":
        await state.update_data(weekdays=[])
        await callback.message.edit_text(
            "Выбери дни недели:", reply_markup=weekdays_kb(set())
        )
    elif freq == "times_per_week":
        await callback.message.edit_text(
            "Сколько раз в неделю?", reply_markup=times_per_week_kb()
        )
    else:  # daily
        await _ask_privacy(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("wd:"))
async def toggle_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    part = callback.data.split(":")[1]
    data = await state.get_data()
    selected = set(data.get("weekdays", []))

    if part == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один день", show_alert=True)
            return
        habit = data.get("habit")
        if habit is None:
            await callback.answer(STALE_WIZARD, show_alert=True)
            return
        habit["freq_value"] = ",".join(str(d) for d in sorted(selected))
        await state.update_data(habit=habit)
        await _ask_privacy(callback.message, state)
        await callback.answer()
        return

    idx = int(part)
    selected.symmetric_difference_update({idx})
    await state.update_data(weekdays=list(selected))
    await callback.message.edit_reply_markup(reply_markup=weekdays_kb(selected))
    await callback.answer()


@router.callback_query(F.data.startswith("tpw:"))
async def pick_times_per_week(callback: CallbackQuery, state: FSMContext) -> None:
    n = callback.data.split(":")[1]
    habit = await _wizard_habit(callback, state)
    if habit is None:
        return
    habit["freq_value"] = n
    await state.update_data(habit=habit)
    await _ask_privacy(callback.message, state)
    await callback.answer()


async def _ask_privacy(message: Message, state: FSMContext) -> None:
    """Шаг выбора приватности — добавлен по требованию: скрыть привычку ото всех."""
    await message.answer(
        "🔐 Кто видит эту привычку?\n\n"
        "• <b>Видят все</b> — привычка, серии и статистика доступны участникам.\n"
        "• <b>Скрыть ото всех</b> — привычку видишь только ты.",
        reply_markup=privacy_kb(),
    )


@router.callback_query(F.data.startswith("priv:"))
async def pick_privacy(callback: CallbackQuery, state: FSMContext) -> None:
    privacy = callback.data.split(":")[1]
    habit = await _wizard_habit(callback, state)
    if habit is None:
        return
    habit["privacy"] = privacy
    await state.update_data(habit=habit)
    await callback.message.edit_text(
        f"Приватность: {PRIVACY_LABEL[privacy]}.\n"
        "Хочешь добавить описание привычки?",
        reply_markup=description_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "desc:skip")
async def desc_skip(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Напоминание?", reply_markup=reminder_kb())
    await callback.answer()


@router.callback_query(F.data == "desc:set")
async def desc_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateHabit.description)
    await callback.message.answer(
        "Опиши, что входит в привычку (например: бег 10 мин, 20 отжиманий, растяжка):"
    )
    await callback.answer()


@router.message(CreateHabit.description)
async def enter_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Описание не может быть пустым. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = data.get("habit")
    if habit is None:
        await message.answer(STALE_WIZARD)
        return
    habit["description"] = text[:500]
    await state.update_data(habit=habit)
    await state.set_state(None)
    await message.answer("Напоминание?", reply_markup=reminder_kb())


@router.callback_query(F.data == "rem:skip")
async def reminder_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Место выполнения?", reply_markup=place_kb())
    await callback.answer()


@router.callback_query(F.data == "rem:set")
async def reminder_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateHabit.reminder)
    await callback.message.answer("Введи время в формате ЧЧ:ММ (например, 08:30):")
    await callback.answer()


@router.message(CreateHabit.reminder)
async def enter_reminder(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not _valid_time(raw):
        await message.answer("Формат времени ЧЧ:ММ, например 07:00. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = data.get("habit")
    if habit is None:
        await message.answer(STALE_WIZARD)
        return
    habit["remind_time"] = raw
    await state.update_data(habit=habit)
    await state.set_state(None)
    await message.answer("Место выполнения?", reply_markup=place_kb())


@router.callback_query(F.data == "place:skip")
async def place_skip(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await _finish_create(callback.message, state, session, user)
    await callback.answer()


@router.callback_query(F.data == "place:set")
async def place_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateHabit.place)
    await callback.message.answer("Введи место (например, «дома», «в зале»):")
    await callback.answer()


@router.message(CreateHabit.place)
async def enter_place(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    habit = data.get("habit")
    if habit is None:
        await message.answer(STALE_WIZARD)
        return
    habit["place"] = (message.text or "").strip()[:128]
    await state.update_data(habit=habit)
    await _finish_create(message, state, session, user)


async def _finish_create(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    h = data.get("habit")
    await state.clear()
    if h is None:
        await message.answer(STALE_WIZARD)
        return

    habit = await create_habit(
        session,
        user_id=user.id,
        title=h.get("title", "Привычка"),
        description=h.get("description"),
        emoji=h.get("emoji", "✅"),
        type=h.get("type", "binary"),
        target=h.get("target"),
        unit=h.get("unit"),
        remind_time=h.get("remind_time"),
        place=h.get("place"),
        frequency=h.get("frequency", "daily"),
        freq_value=h.get("freq_value"),
        privacy=h.get("privacy", "public"),
    )

    # Планируем напоминание, если указано время.
    if habit.remind_time:
        try:
            from services.scheduler import schedule_habit_reminder

            schedule_habit_reminder(message.bot, habit, user)
        except Exception:  # планировщик не критичен для создания привычки
            pass

    summary = _habit_summary(habit)
    await message.answer("🎉 <b>Привычка создана!</b>\n\n" + summary, reply_markup=home_kb())


def _habit_summary(habit) -> str:
    lines = [f"{habit.emoji} <b>{esc(habit.title)}</b>"]
    if habit.description:
        lines.append(f"📝 {esc(habit.description)}")
    if habit.type == "quantitative":
        lines.append(f"Цель: {habit.target} {esc(habit.unit or '')}".strip())
    freq_map = {"daily": "каждый день", "weekdays": "по дням недели",
                "times_per_week": f"{habit.freq_value} раз в неделю"}
    lines.append(f"Периодичность: {freq_map.get(habit.frequency, habit.frequency)}")
    if habit.frequency == "weekdays" and habit.freq_value:
        days = ", ".join(WEEKDAY_NAMES[int(d)] for d in habit.freq_value.split(","))
        lines.append(f"Дни: {days}")
    if habit.remind_time:
        lines.append(f"Напоминание: {habit.remind_time}")
    if habit.place:
        lines.append(f"Место: {esc(habit.place)}")
    lines.append(f"Приватность: {PRIVACY_LABEL.get(habit.privacy, habit.privacy)}")
    return "\n".join(lines)


def _valid_time(raw: str) -> bool:
    parts = raw.split(":")
    if len(parts) != 2:
        return False
    h, m = parts
    return h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59


# ---------- Действия с привычкой ----------

@router.callback_query(F.data.startswith("hb:open:"))
async def open_habit(callback: CallbackQuery, session: AsyncSession) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await callback.message.answer(
        _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hb:tracker:"))
async def habit_tracker(callback: CallbackQuery, session: AsyncSession) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    tracker = await render_tracker(session, habit)
    await callback.message.answer(
        f"📈 <b>{habit.emoji} {esc(habit.title)}</b>\n<pre>{esc(tracker)}</pre>",
        reply_markup=home_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hb:priv:"))
async def change_privacy(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, habit_id, new_priv = callback.data.split(":")
    habit = await get_habit(session, int(habit_id))
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await update_habit(session, habit, privacy=new_priv)
    await callback.message.edit_text(
        _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )
    await callback.answer(
        "Скрыто ото всех 🔒" if new_priv == "private" else "Теперь видят все 👥"
    )


@router.callback_query(F.data.startswith("hb:archive:"))
async def archive(callback: CallbackQuery, session: AsyncSession) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await archive_habit(session, habit)
    try:
        from services.scheduler import remove_habit_reminder

        remove_habit_reminder(habit.id)
    except Exception:
        pass
    await callback.message.edit_text(f"🗄 «{esc(habit.title)}» перенесена в архив.")
    await callback.answer()


@router.callback_query(F.data == "hb:arclist")
async def show_archive(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    habits = await list_archived_habits(session, user.id)
    if not habits:
        await callback.message.answer(
            "В архиве пусто. Сюда попадают привычки, которые ты убрал из активных."
        )
        await callback.answer()
        return
    await callback.message.answer(
        "🗄 <b>Архив</b>\nНажми на привычку, чтобы вернуть её в активные:",
        reply_markup=archived_list_kb(habits),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hb:restore:"))
async def restore(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await restore_habit(session, habit)
    # Возвращаем напоминание, если у привычки задано время.
    if habit.remind_time:
        try:
            from services.scheduler import schedule_habit_reminder

            schedule_habit_reminder(callback.bot, habit, user)
        except Exception:
            pass
    habits = await list_archived_habits(session, user.id)
    if habits:
        await safe_edit_text(
            callback.message,
            "🗄 <b>Архив</b>\nНажми на привычку, чтобы вернуть её в активные:",
            reply_markup=archived_list_kb(habits),
        )
    else:
        await safe_edit_text(callback.message, "🗄 Архив пуст.")
    await callback.answer(f"♻️ «{habit.title}» снова в активных")


def _resync_reminder(bot, habit, user) -> None:
    """Приводит задачу напоминания в соответствие с habit.remind_time."""
    try:
        from services.scheduler import remove_habit_reminder, schedule_habit_reminder

        if habit.remind_time:
            schedule_habit_reminder(bot, habit, user)
        else:
            remove_habit_reminder(habit.id)
    except Exception:
        pass


@router.callback_query(F.data.startswith("hb:edit:"))
async def edit_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await safe_edit_text(
        callback.message,
        _habit_summary(habit) + "\n\nЧто изменить?",
        reply_markup=habit_edit_kb(habit),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("he:rem:"))
async def edit_reminder_start(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = int(callback.data.split(":")[2])
    await state.set_state(EditHabit.reminder)
    await state.update_data(edit_id=habit_id)
    await callback.message.answer(
        "Введи новое время напоминания в формате ЧЧ:ММ (например, 08:30) "
        "или напиши «выкл», чтобы отключить:"
    )
    await callback.answer()


@router.message(EditHabit.reminder)
async def edit_reminder_finish(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    raw = (message.text or "").strip()
    off = raw.lower() in {"выкл", "off", "нет", "-"}
    if not off and not _valid_time(raw):
        await message.answer(
            "Формат ЧЧ:ММ (например 07:00) или «выкл». Попробуй ещё раз:"
        )
        return
    data = await state.get_data()
    habit = await get_habit(session, data.get("edit_id"))
    await state.clear()
    if not habit:
        await message.answer(STALE_WIZARD)
        return
    await update_habit(session, habit, remind_time=None if off else raw)
    _resync_reminder(message.bot, habit, user)
    note = "Напоминание отключено." if off else f"Напоминание: {raw}."
    await message.answer(
        f"✅ {note}\n\n" + _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )


@router.callback_query(F.data.startswith("he:target:"))
async def edit_target_start(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = int(callback.data.split(":")[2])
    await state.set_state(EditHabit.target)
    await state.update_data(edit_id=habit_id)
    await callback.message.answer("Введи новую дневную цель (число):")
    await callback.answer()


@router.message(EditHabit.target)
async def edit_target_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Нужно положительное число. Попробуй ещё раз:")
        return
    data = await state.get_data()
    habit = await get_habit(session, data.get("edit_id"))
    await state.clear()
    if not habit:
        await message.answer(STALE_WIZARD)
        return
    await update_habit(session, habit, target=int(raw))
    await message.answer(
        "✅ Цель обновлена.\n\n" + _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )


@router.callback_query(F.data.startswith("he:desc:"))
async def edit_desc_start(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = int(callback.data.split(":")[2])
    await state.set_state(EditHabit.description)
    await state.update_data(edit_id=habit_id)
    await callback.message.answer(
        "Введи новое описание (или напиши «убрать», чтобы удалить):"
    )
    await callback.answer()


@router.message(EditHabit.description)
async def edit_desc_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    habit = await get_habit(session, data.get("edit_id"))
    await state.clear()
    if not habit:
        await message.answer(STALE_WIZARD)
        return
    clear = raw.lower() in {"убрать", "удалить", "очистить", "-"}
    await update_habit(session, habit, description=None if clear else raw[:500])
    note = "Описание убрано." if clear else "Описание обновлено."
    await message.answer(
        f"✅ {note}\n\n" + _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )


@router.callback_query(F.data.startswith("he:freq:"))
async def edit_frequency_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    habit_id = int(callback.data.split(":")[2])
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await safe_edit_text(
        callback.message,
        "Как часто выполнять?",
        reply_markup=edit_frequency_kb(habit_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hef:"))
async def edit_frequency_pick(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, habit_id, freq = callback.data.split(":")
    habit_id = int(habit_id)
    habit = await get_habit(session, habit_id)
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    if freq == "weekdays":
        await state.update_data(edit_id=habit_id, edit_weekdays=[])
        await safe_edit_text(
            callback.message, "Выбери дни недели:", reply_markup=edit_weekdays_kb(set())
        )
    elif freq == "times_per_week":
        await safe_edit_text(
            callback.message,
            "Сколько раз в неделю?",
            reply_markup=edit_times_per_week_kb(habit_id),
        )
    else:  # daily
        await update_habit(session, habit, frequency="daily", freq_value=None)
        await safe_edit_text(
            callback.message,
            "✅ Теперь каждый день.\n\n" + _habit_summary(habit),
            reply_markup=habit_actions_kb(habit.id, habit.privacy),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("hewd:"))
async def edit_weekday_toggle(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    part = callback.data.split(":")[1]
    data = await state.get_data()
    habit_id = data.get("edit_id")
    if habit_id is None:
        await callback.answer(STALE_WIZARD, show_alert=True)
        return
    selected = set(data.get("edit_weekdays", []))

    if part == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один день", show_alert=True)
            return
        habit = await get_habit(session, habit_id)
        await state.clear()
        if not habit:
            await callback.answer("Привычка не найдена", show_alert=True)
            return
        value = ",".join(str(d) for d in sorted(selected))
        await update_habit(session, habit, frequency="weekdays", freq_value=value)
        await safe_edit_text(
            callback.message,
            "✅ Дни обновлены.\n\n" + _habit_summary(habit),
            reply_markup=habit_actions_kb(habit.id, habit.privacy),
        )
        await callback.answer()
        return

    selected.symmetric_difference_update({int(part)})
    await state.update_data(edit_weekdays=list(selected))
    from utils import safe_edit_markup

    await safe_edit_markup(callback.message, edit_weekdays_kb(selected))
    await callback.answer()


@router.callback_query(F.data.startswith("hetpw:"))
async def edit_times_per_week(callback: CallbackQuery, session: AsyncSession) -> None:
    _, habit_id, n = callback.data.split(":")
    habit = await get_habit(session, int(habit_id))
    if not habit:
        await callback.answer("Привычка не найдена", show_alert=True)
        return
    await update_habit(session, habit, frequency="times_per_week", freq_value=n)
    await safe_edit_text(
        callback.message,
        f"✅ Теперь {n} раз в неделю.\n\n" + _habit_summary(habit),
        reply_markup=habit_actions_kb(habit.id, habit.privacy),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hb:rename:"))
async def rename_start(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = int(callback.data.split(":")[2])
    await state.set_state(RenameHabit.title)
    await state.update_data(rename_id=habit_id)
    await callback.message.answer("Введи новое название:")
    await callback.answer()


@router.message(RenameHabit.title)
async def rename_finish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым:")
        return
    data = await state.get_data()
    rename_id = data.get("rename_id")
    habit = await get_habit(session, rename_id) if rename_id else None
    await state.clear()
    if habit:
        await update_habit(session, habit, title=title[:128])
        await message.answer(
            f"✅ Переименовано в «{esc(title)}».", reply_markup=home_kb()
        )
