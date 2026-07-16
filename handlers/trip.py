"""Trip handler: checklists, templates, packing lists."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import User
from db.trip_queries import (
    add_checklist_item,
    add_template_items,
    add_trip,
    check_all,
    count_trips,
    delete_trip,
    get_trip,
    list_trips,
    toggle_item,
    uncheck_all,
    update_trip_status,
)
from services.trip import (
    ITEM_CATEGORIES,
    TEMPLATES,
    TRIP_STATUSES,
    format_checklist,
)
from states import TripFlow
from utils import esc

router = Router()

ADMIN_TG_ID = config.admin_id


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


def _trip_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✈️ Активные", callback_data="trip:active")
    kb.button(text="📋 Все", callback_data="trip:all:0")
    kb.button(text="➕ Новая", callback_data="trip:add")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 1, 2)
    return kb


def _back_trip_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


def _trip_view_kb(trip_id: int, has_items: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if has_items:
        kb.button(text="☑️ Отметить", callback_data=f"trip:chk:{trip_id}:0")
    kb.button(text="➕ Пункт", callback_data=f"trip:ai:{trip_id}")
    kb.button(text="📋 Шаблон", callback_data=f"trip:tpl:{trip_id}")
    kb.button(text="🔄 Статус", callback_data=f"trip:st:{trip_id}")
    if has_items:
        kb.button(text="✅ Всё ✓", callback_data=f"trip:ca:{trip_id}")
        kb.button(text="⬜ Сброс", callback_data=f"trip:ua:{trip_id}")
    kb.button(text="🗑 Удалить", callback_data=f"trip:del:{trip_id}")
    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    if has_items:
        kb.adjust(1, 2, 1, 2, 1, 1)
    else:
        kb.adjust(2, 1, 1, 1)
    return kb


# ---- Меню ----

@router.callback_query(F.data == "trip:menu")
async def cb_trip_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()

    trips = await list_trips(session, user.id)
    active = [t for t in trips if t.status in ("planning", "packing", "active")]

    text = (
        f"✈️ <b>Поездки</b>\n\n"
        f"Всего: {len(trips)}\n"
        f"Активных: {len(active)}"
    )
    await callback.message.answer(text, reply_markup=_trip_menu_kb().as_markup())


# ---- Активные поездки ----

@router.callback_query(F.data == "trip:active")
async def cb_active(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    trips = await list_trips(session, user.id, active_only=True)
    if not trips:
        await callback.message.answer(
            "✈️ <b>Активные поездки</b>\n\nНет активных. Создай новую!",
            reply_markup=_back_trip_kb().as_markup(),
        )
        return

    lines = ["✈️ <b>Активные поездки</b>\n"]
    kb = InlineKeyboardBuilder()
    for trip in trips:
        status = TRIP_STATUSES.get(trip.status, trip.status)
        items = trip.items or []
        checked = sum(1 for i in items if i.checked)
        total = len(items)
        pct = f" ({checked}/{total})" if total else ""
        dest = f" → {trip.destination}" if trip.destination else ""
        lines.append(f"{status} <b>{esc(trip.name)}</b>{dest}{pct}")
        kb.button(text=f"🧳 {trip.name[:22]}", callback_data=f"trip:v:{trip.id}")

    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(*([1] * len(trips)), 2)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Все поездки ----

@router.callback_query(F.data.startswith("trip:all:"))
async def cb_all_trips(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    page = int(callback.data.split(":")[2])
    page_size = 10
    trips = await list_trips(session, user.id)
    total = len(trips)
    start = page * page_size
    page_trips = trips[start : start + page_size]
    has_more = start + page_size < total

    if not trips:
        await callback.message.answer(
            "📋 <b>Все поездки</b>\n\nПока нет.",
            reply_markup=_back_trip_kb().as_markup(),
        )
        return

    lines = [f"📋 <b>Все поездки</b> ({total})\n"]
    kb = InlineKeyboardBuilder()
    for trip in page_trips:
        status = TRIP_STATUSES.get(trip.status, trip.status)
        dest = f" → {trip.destination}" if trip.destination else ""
        lines.append(f"{status} {esc(trip.name)}{dest}")
        kb.button(text=f"🧳 {trip.name[:22]}", callback_data=f"trip:v:{trip.id}")

    if page > 0:
        kb.button(text="⬅️", callback_data=f"trip:all:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"trip:all:{page + 1}")
    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    trip_rows = [1] * len(page_trips)
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    if nav:
        trip_rows.append(nav)
    trip_rows.append(2)
    kb.adjust(*trip_rows)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Просмотр поездки (чеклист) ----

@router.callback_query(F.data.startswith("trip:v:"))
async def cb_view_trip(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    trip_id = int(callback.data.split(":")[2])
    trip = await get_trip(session, trip_id)
    if not trip:
        await callback.message.answer("Не найдена.", reply_markup=_back_trip_kb().as_markup())
        return

    items = sorted(trip.items or [], key=lambda x: (x.category, x.sort_order))
    text = format_checklist(items, trip.name)

    if trip.destination:
        text += f"\n📍 {esc(trip.destination)}"
    status = TRIP_STATUSES.get(trip.status, trip.status)
    text += f"\n{status}"

    await callback.message.answer(
        text, reply_markup=_trip_view_kb(trip_id, bool(items)).as_markup()
    )


# ---- Отметка пунктов (пагинация) ----

@router.callback_query(F.data.startswith("trip:chk:"))
async def cb_check_items(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    parts = callback.data.split(":")
    trip_id = int(parts[2])
    page = int(parts[3])
    page_size = 12

    trip = await get_trip(session, trip_id)
    if not trip:
        await callback.message.answer("Не найдена.", reply_markup=_back_trip_kb().as_markup())
        return

    items = sorted(trip.items or [], key=lambda x: (x.category, x.sort_order))
    total = len(items)
    start = page * page_size
    page_items = items[start : start + page_size]
    has_more = start + page_size < total

    kb = InlineKeyboardBuilder()
    for item in page_items:
        mark = "✅" if item.checked else "⬜"
        kb.button(text=f"{mark} {item.text[:28]}", callback_data=f"trip:ti:{trip_id}:{item.id}:{page}")
    if page > 0:
        kb.button(text="⬅️", callback_data=f"trip:chk:{trip_id}:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"trip:chk:{trip_id}:{page + 1}")
    kb.button(text="🧳 Назад", callback_data=f"trip:v:{trip_id}")
    item_rows = [1] * len(page_items)
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    if nav:
        item_rows.append(nav)
    item_rows.append(1)
    kb.adjust(*item_rows)

    checked = sum(1 for i in items if i.checked)
    pct = int(checked / total * 100) if total else 0
    await callback.message.answer(
        f"☑️ <b>Отметить пункты</b> ({checked}/{total} — {pct}%)",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("trip:ti:"))
async def cb_toggle_item(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    parts = callback.data.split(":")
    trip_id = int(parts[2])
    item_id = int(parts[3])
    page = int(parts[4])

    item = await toggle_item(session, item_id)
    if item:
        mark = "✅" if item.checked else "⬜"
        await callback.answer(f"{mark} {item.text[:30]}")
    else:
        await callback.answer("Не найден")
        return

    trip = await get_trip(session, trip_id)
    if not trip:
        return

    items = sorted(trip.items or [], key=lambda x: (x.category, x.sort_order))
    total = len(items)
    page_size = 12
    start = page * page_size
    page_items = items[start : start + page_size]
    has_more = start + page_size < total

    kb = InlineKeyboardBuilder()
    for it in page_items:
        m = "✅" if it.checked else "⬜"
        kb.button(text=f"{m} {it.text[:28]}", callback_data=f"trip:ti:{trip_id}:{it.id}:{page}")
    if page > 0:
        kb.button(text="⬅️", callback_data=f"trip:chk:{trip_id}:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"trip:chk:{trip_id}:{page + 1}")
    kb.button(text="🧳 Назад", callback_data=f"trip:v:{trip_id}")
    item_rows = [1] * len(page_items)
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    if nav:
        item_rows.append(nav)
    item_rows.append(1)
    kb.adjust(*item_rows)

    checked = sum(1 for i in items if i.checked)
    pct = int(checked / total * 100) if total else 0
    try:
        await callback.message.edit_text(
            f"☑️ <b>Отметить пункты</b> ({checked}/{total} — {pct}%)",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        pass


# ---- Check all / Uncheck all ----

@router.callback_query(F.data.startswith("trip:ca:"))
async def cb_check_all(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    trip_id = int(callback.data.split(":")[2])
    count = await check_all(session, trip_id)
    await callback.answer(f"✅ Всё отмечено ({count})")


@router.callback_query(F.data.startswith("trip:ua:"))
async def cb_uncheck_all(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    trip_id = int(callback.data.split(":")[2])
    count = await uncheck_all(session, trip_id)
    await callback.answer(f"⬜ Сброс ({count})")


# ---- Применить шаблон ----

@router.callback_query(F.data.startswith("trip:tpl:"))
async def cb_pick_template(callback: CallbackQuery) -> None:
    trip_id = int(callback.data.split(":")[2])
    await callback.answer()

    kb = InlineKeyboardBuilder()
    for code, (label, _) in TEMPLATES.items():
        kb.button(text=label, callback_data=f"trip:usetpl:{trip_id}:{code}")
    kb.button(text="🧳 Назад", callback_data=f"trip:v:{trip_id}")
    kb.adjust(2, 2, 1)

    await callback.message.answer("Выбери шаблон:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("trip:usetpl:"))
async def cb_use_template(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    parts = callback.data.split(":")
    trip_id = int(parts[2])
    code = parts[3]

    tpl = TEMPLATES.get(code)
    if not tpl:
        await callback.answer("Шаблон не найден", show_alert=True)
        return

    label, items = tpl
    count = await add_template_items(session, trip_id, items)
    await callback.answer(f"{label}: +{count} пунктов")

    trip = await get_trip(session, trip_id)
    if trip:
        all_items = sorted(trip.items or [], key=lambda x: (x.category, x.sort_order))
        text = format_checklist(all_items, trip.name)
        await callback.message.answer(
            text, reply_markup=_trip_view_kb(trip_id, bool(all_items)).as_markup()
        )


# ---- Смена статуса ----

@router.callback_query(F.data.startswith("trip:st:"))
async def cb_change_status(callback: CallbackQuery) -> None:
    trip_id = int(callback.data.split(":")[2])
    await callback.answer()

    kb = InlineKeyboardBuilder()
    for code, label in TRIP_STATUSES.items():
        kb.button(text=label, callback_data=f"trip:setst:{trip_id}:{code}")
    kb.button(text="🧳 Назад", callback_data=f"trip:v:{trip_id}")
    kb.adjust(2, 2, 1)
    await callback.message.answer("Выбери статус:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("trip:setst:"))
async def cb_set_status(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    parts = callback.data.split(":")
    trip_id = int(parts[2])
    status = parts[3]
    trip = await update_trip_status(session, trip_id, status)
    if trip:
        label = TRIP_STATUSES.get(status, status)
        await callback.answer(f"{label}")
    else:
        await callback.answer("Не найдена", show_alert=True)


# ---- Удалить поездку ----

@router.callback_query(F.data.startswith("trip:del:"))
async def cb_delete_trip(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    trip_id = int(callback.data.split(":")[2])
    if await delete_trip(session, trip_id):
        await callback.answer("Удалена")
        await callback.message.answer("🗑 Поездка удалена.", reply_markup=_back_trip_kb().as_markup())
    else:
        await callback.answer("Не найдена", show_alert=True)


# ---- Добавить поездку ----

@router.callback_query(F.data == "trip:add")
async def cb_add_trip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(TripFlow.trip_name)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="trip:menu")
    await callback.message.answer(
        "✈️ <b>Новая поездка</b>\n\nНазвание (например: Турция июль):",
        reply_markup=kb.as_markup(),
    )


@router.message(TripFlow.trip_name)
async def process_trip_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:128]
    if not name:
        await message.answer("Введи название.")
        return
    await state.update_data(trip_name=name)
    await state.set_state(TripFlow.trip_dest)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="trip:dest:skip")
    kb.button(text="❌ Отмена", callback_data="trip:menu")
    kb.adjust(1, 1)
    await message.answer(
        f"✈️ <b>{esc(name)}</b>\n\nКуда? (город/страна или пропусти)",
        reply_markup=kb.as_markup(),
    )


@router.message(TripFlow.trip_dest)
async def process_trip_dest(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    dest = message.text.strip()[:256]
    await state.update_data(trip_dest=dest if dest else None)
    await _save_trip(message, session, user, state)


@router.callback_query(F.data == "trip:dest:skip")
async def cb_dest_skip(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.update_data(trip_dest=None)
    await callback.answer()
    await _save_trip(callback.message, session, user, state)


async def _save_trip(
    target: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    name = data.get("trip_name")
    if not name:
        await target.answer("Ошибка.", reply_markup=_back_trip_kb().as_markup())
        await state.clear()
        return

    trip = await add_trip(session, user.id, name, data.get("trip_dest"))
    await state.clear()

    kb = InlineKeyboardBuilder()
    for code, (label, _) in TEMPLATES.items():
        kb.button(text=label, callback_data=f"trip:usetpl:{trip.id}:{code}")
    kb.button(text="➕ Свой пункт", callback_data=f"trip:ai:{trip.id}")
    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    kb.adjust(2, 2, 1, 1)

    dest = f"\n📍 {esc(data.get('trip_dest'))}" if data.get("trip_dest") else ""
    await target.answer(
        f"✅ Создана: <b>{esc(name)}</b>{dest}\n\nВыбери шаблон или добавь свои пункты:",
        reply_markup=kb.as_markup(),
    )


# ---- Добавить свой пункт ----

@router.callback_query(F.data.startswith("trip:ai:"))
async def cb_add_item_start(callback: CallbackQuery, state: FSMContext) -> None:
    trip_id = int(callback.data.split(":")[2])
    await state.update_data(add_trip_id=trip_id)
    await state.set_state(TripFlow.add_item)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data=f"trip:v:{trip_id}")
    await callback.message.answer(
        "➕ Введи пункт (или несколько через запятую):\n"
        "<code>Зонтик, плед, настольная игра</code>",
        reply_markup=kb.as_markup(),
    )


@router.message(TripFlow.add_item)
async def process_add_item(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    trip_id = data.get("add_trip_id")
    if not trip_id:
        await message.answer("Ошибка.")
        await state.clear()
        return

    texts = [t.strip() for t in message.text.split(",") if t.strip()]
    if not texts:
        await message.answer("Введи хотя бы один пункт.")
        return

    for text in texts:
        await add_checklist_item(session, trip_id, text[:256])

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data=f"trip:v:{trip_id}")
    await message.answer(
        f"➕ Добавлено: {len(texts)} пунктов. Ещё? Или нажми Готово.",
        reply_markup=kb.as_markup(),
    )
