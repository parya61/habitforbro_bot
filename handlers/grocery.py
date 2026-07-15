"""Grocery handler: shopping lists, mark-bought, add items."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.grocery_queries import (
    add_item,
    count_items,
    delete_item,
    group_by_store,
    list_all_items,
    list_due_items,
    mark_bought_all,
    mark_bought_by_store,
    mark_bought_item,
    toggle_item,
)
from db.models import User
from services.grocery import (
    CODE_BY_STORE,
    FREQ_OPTIONS,
    STORE_CODES,
    STORE_NAMES,
    STORE_ORDER,
    ensure_seeded,
    format_shopping_list,
)
from states import GroceryFlow
from utils import esc, user_today

router = Router()

ADMIN_TG_ID = config.admin_id


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


def _grocery_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Что купить", callback_data="groc:list")
    kb.button(text="📋 Каталог", callback_data="groc:cat:0")
    kb.button(text="➕ Добавить", callback_data="groc:add")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 1, 2)
    return kb


def _back_grocery_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Продукты", callback_data="groc:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


# ---- Меню продуктов ----

@router.callback_query(F.data == "groc:menu")
async def cb_grocery_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await ensure_seeded(session, user.id)

    due = await list_due_items(session, user.id, user_today(user))
    total = await count_items(session, user.id)

    text = (
        f"🛒 <b>Продукты</b>\n\n"
        f"В каталоге: {total} позиций\n"
        f"Пора купить: <b>{len(due)}</b> позиций"
    )
    await callback.message.answer(text, reply_markup=_grocery_menu_kb().as_markup())


# ---- Список покупок ----

@router.callback_query(F.data == "groc:list")
async def cb_shopping_list(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    today = user_today(user)
    due = await list_due_items(session, user.id, today)
    grouped = group_by_store(due)
    text = format_shopping_list(grouped, len(due))

    kb = InlineKeyboardBuilder()
    for store in STORE_ORDER:
        items = grouped.get(store)
        if items:
            code = CODE_BY_STORE[store]
            kb.button(
                text=f"✅ Купил: {STORE_NAMES[store]}",
                callback_data=f"groc:b:{code}",
            )
    if due:
        kb.button(text="✅ Всё купил", callback_data="groc:b:a")
    kb.button(text="🛒 Продукты", callback_data="groc:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    store_count = sum(1 for s in STORE_ORDER if s in grouped)
    kb.adjust(*([1] * store_count), 1 if due else 0, 2)

    await callback.message.answer(text, reply_markup=kb.as_markup())


# ---- Отметить купленное ----

@router.callback_query(F.data.startswith("groc:b:"))
async def cb_mark_bought(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return

    code = callback.data.split(":")[2]
    today = user_today(user)

    if code == "a":
        count = await mark_bought_all(session, user.id, today)
        await callback.answer(f"Всё отмечено! ({count} поз.)")
    else:
        store = STORE_CODES.get(code)
        if not store:
            await callback.answer("Неизвестный магазин", show_alert=True)
            return
        count = await mark_bought_by_store(session, user.id, store, today)
        await callback.answer(f"{STORE_NAMES[store]}: {count} поз. ✅")

    due = await list_due_items(session, user.id, today)
    grouped = group_by_store(due)
    text = format_shopping_list(grouped, len(due))

    kb = InlineKeyboardBuilder()
    for store in STORE_ORDER:
        items = grouped.get(store)
        if items:
            c = CODE_BY_STORE[store]
            kb.button(
                text=f"✅ Купил: {STORE_NAMES[store]}",
                callback_data=f"groc:b:{c}",
            )
    if due:
        kb.button(text="✅ Всё купил", callback_data="groc:b:a")
    kb.button(text="🛒 Продукты", callback_data="groc:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    store_count = sum(1 for s in STORE_ORDER if s in grouped)
    kb.adjust(*([1] * store_count), 1 if due else 0, 2)

    await callback.message.answer(text, reply_markup=kb.as_markup())


# ---- Каталог ----

@router.callback_query(F.data.startswith("groc:cat:"))
async def cb_catalog(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    page = int(callback.data.split(":")[2])
    page_size = 15
    items = await list_all_items(session, user.id, active_only=False)
    total = len(items)
    start = page * page_size
    page_items = items[start : start + page_size]
    has_more = start + page_size < total

    lines = [f"📋 <b>Каталог</b> ({total} поз.)\n"]
    for item in page_items:
        status = "" if item.active else " ❌"
        store = f" ({item.usual_store})" if item.usual_store else ""
        freq = f" / {item.buy_freq_days}д" if item.buy_freq_days != 7 else ""
        whom = " 👩" if item.for_whom == "wife" else ""
        whom = " 👨" if item.for_whom == "me" else whom
        lines.append(f"{item.icon} {esc(item.name)}{store}{freq}{whom}{status}")

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"groc:cat:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"groc:cat:{page + 1}")
    kb.button(text="🛒 Продукты", callback_data="groc:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    kb.adjust(nav, 2) if nav else kb.adjust(2)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Добавить продукт ----

@router.callback_query(F.data == "groc:add")
async def cb_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(GroceryFlow.add_name)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="groc:menu")
    await callback.message.answer(
        "➕ <b>Новый продукт</b>\n\nВведи название:",
        reply_markup=kb.as_markup(),
    )


@router.message(GroceryFlow.add_name)
async def process_add_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:128]
    if not name:
        await message.answer("Введи название продукта.")
        return
    await state.update_data(item_name=name)
    await state.set_state(None)

    kb = InlineKeyboardBuilder()
    for days, label in FREQ_OPTIONS:
        kb.button(text=label, callback_data=f"groc:freq:{days}")
    kb.button(text="❌ Отмена", callback_data="groc:menu")
    kb.adjust(4, 1)
    await message.answer(
        f"📦 <b>{esc(name)}</b>\n\nКак часто покупать?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("groc:freq:"))
async def cb_add_freq(callback: CallbackQuery, state: FSMContext) -> None:
    freq = int(callback.data.split(":")[2])
    await state.update_data(freq_days=freq)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    for code, store in STORE_CODES.items():
        kb.button(text=STORE_NAMES[store], callback_data=f"groc:st:{code}")
    kb.button(text="❌ Отмена", callback_data="groc:menu")
    kb.adjust(3, 1)
    await callback.message.answer(
        "В каком магазине обычно покупаешь?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("groc:st:"))
async def cb_add_store(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    code = callback.data.split(":")[2]
    store = STORE_CODES.get(code, "пятёрочка")

    data = await state.get_data()
    name = data.get("item_name")
    freq = data.get("freq_days", 7)

    if not name:
        await callback.answer("Сессия устарела, начни заново.", show_alert=True)
        await state.clear()
        return

    await callback.answer()
    item = await add_item(session, user.id, name, store, freq)
    await state.clear()

    await callback.message.answer(
        f"✅ Добавлено: <b>{esc(name)}</b>\n"
        f"📍 {STORE_NAMES[store]} / каждые {freq} дн.",
        reply_markup=_back_grocery_kb().as_markup(),
    )
