"""Cafe handler: places, visits, ratings, wishlist."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.cafe_queries import (
    add_cafe,
    add_visit,
    cafe_stats,
    count_cafes,
    delete_cafe,
    get_cafe,
    list_cafes,
    list_visits,
    toggle_wishlist,
    top_cafes,
)
from db.models import User
from services.cafe import (
    CUISINE_TYPES,
    PRICE_LEVELS,
    format_cafe_card,
    fmt_price_level,
    fmt_rating,
)
from services.finance import fmt_money
from states import CafeFlow
from utils import esc, user_today

router = Router()

ADMIN_TG_ID = config.admin_id


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


# ---- Клавиатуры ----

def _cafe_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Топ кафе", callback_data="cafe:top")
    kb.button(text="📌 Вишлист", callback_data="cafe:wish")
    kb.button(text="📜 Визиты", callback_data="cafe:vis:0")
    kb.button(text="📋 Все кафе", callback_data="cafe:all:0")
    kb.button(text="➕ Добавить", callback_data="cafe:add")
    kb.button(text="✏️ Был сегодня", callback_data="cafe:logpick")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 2, 2, 2)
    return kb


def _back_cafe_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


# ---- Меню ----

@router.callback_query(F.data == "cafe:menu")
async def cb_cafe_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()

    total = await count_cafes(session, user.id)
    cafes = await list_cafes(session, user.id)
    visited = sum(1 for c in cafes if not c.is_wishlist and c.visits)
    wishlist = sum(1 for c in cafes if c.is_wishlist)

    text = (
        f"☕ <b>Кафе и рестораны</b>\n\n"
        f"Всего мест: {total}\n"
        f"Посещённых: {visited}\n"
        f"В вишлисте: {wishlist}"
    )
    await callback.message.answer(text, reply_markup=_cafe_menu_kb().as_markup())


# ---- Топ кафе ----

@router.callback_query(F.data == "cafe:top")
async def cb_top(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    top = await top_cafes(session, user.id)
    if not top:
        await callback.message.answer(
            "🏆 <b>Топ кафе</b>\n\nПока нет посещённых мест.",
            reply_markup=_back_cafe_kb().as_markup(),
        )
        return

    lines = ["🏆 <b>Топ кафе</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (cafe, visits, avg_r, avg_s) in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        r = f" ⭐{avg_r:.1f}" if avg_r else ""
        s = f" ~{fmt_money(avg_s)}" if avg_s else ""
        cuisine = f" ({cafe.cuisine})" if cafe.cuisine else ""
        lines.append(f"{medal} <b>{esc(cafe.name)}</b>{cuisine}{r}{s} — {visits} виз.")

    await callback.message.answer(
        "\n".join(lines), reply_markup=_back_cafe_kb().as_markup()
    )


# ---- Вишлист ----

@router.callback_query(F.data == "cafe:wish")
async def cb_wishlist(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    cafes = await list_cafes(session, user.id, wishlist_only=True)
    if not cafes:
        await callback.message.answer(
            "📌 <b>Вишлист</b>\n\nПусто. Добавь кафе с флагом «хочу сходить».",
            reply_markup=_back_cafe_kb().as_markup(),
        )
        return

    lines = ["📌 <b>Хочу сходить</b>\n"]
    for cafe in cafes:
        addr = f" — {cafe.address}" if cafe.address else ""
        cuisine = f" ({cafe.cuisine})" if cafe.cuisine else ""
        lines.append(f"☕ {esc(cafe.name)}{cuisine}{addr}")

    kb = InlineKeyboardBuilder()
    for cafe in cafes[:8]:
        kb.button(text=f"✏️ {cafe.name[:20]}", callback_data=f"cafe:v:{cafe.id}")
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    rows = [1] * min(len(cafes), 8) + [2]
    kb.adjust(*rows)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Все кафе (пагинация) ----

@router.callback_query(F.data.startswith("cafe:all:"))
async def cb_all_cafes(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    page = int(callback.data.split(":")[2])
    page_size = 10
    cafes = await list_cafes(session, user.id)
    total = len(cafes)
    start = page * page_size
    page_cafes = cafes[start : start + page_size]
    has_more = start + page_size < total

    if not cafes:
        await callback.message.answer(
            "📋 <b>Все кафе</b>\n\nПока пусто.",
            reply_markup=_back_cafe_kb().as_markup(),
        )
        return

    lines = [f"📋 <b>Все кафе</b> ({total} мест)\n"]
    for cafe in page_cafes:
        visits = len(cafe.visits) if cafe.visits else 0
        ratings = [v.rating for v in (cafe.visits or []) if v.rating]
        avg_r = sum(ratings) / len(ratings) if ratings else None
        r = f" ⭐{avg_r:.1f}" if avg_r else ""
        wl = " 📌" if cafe.is_wishlist else ""
        v = f" ({visits} виз.)" if visits else ""
        lines.append(f"☕ {esc(cafe.name)}{r}{v}{wl}")

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"cafe:all:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"cafe:all:{page + 1}")
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    kb.adjust(nav, 2) if nav else kb.adjust(2)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Карточка кафе ----

@router.callback_query(F.data.startswith("cafe:v:"))
async def cb_view_cafe(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    cafe_id = int(callback.data.split(":")[2])
    cafe = await get_cafe(session, cafe_id)
    if not cafe:
        await callback.message.answer("Кафе не найдено.", reply_markup=_back_cafe_kb().as_markup())
        return

    count, avg_r, avg_s = await cafe_stats(session, cafe_id)
    text = format_cafe_card(cafe, count, avg_r, avg_s)

    if cafe.visits:
        text += "\n\n<b>Последние визиты:</b>"
        for v in sorted(cafe.visits, key=lambda x: x.visit_date, reverse=True)[:5]:
            d = v.visit_date.strftime("%d.%m")
            r = f" ⭐{v.rating}" if v.rating else ""
            s = f" {fmt_money(v.spent)}" if v.spent else ""
            dish = f" — {v.dish}" if v.dish else ""
            text += f"\n  {d}{r}{s}{dish}"

    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Был сегодня", callback_data=f"cafe:log:{cafe_id}")
    wl_text = "❌ Из вишлиста" if cafe.is_wishlist else "📌 В вишлист"
    kb.button(text=wl_text, callback_data=f"cafe:wl:{cafe_id}")
    kb.button(text="🗑 Удалить", callback_data=f"cafe:del:{cafe_id}")
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.adjust(1, 2, 1)

    await callback.message.answer(text, reply_markup=kb.as_markup())


# ---- Toggle wishlist ----

@router.callback_query(F.data.startswith("cafe:wl:"))
async def cb_toggle_wishlist(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return

    cafe_id = int(callback.data.split(":")[2])
    cafe = await toggle_wishlist(session, cafe_id)
    if cafe:
        status = "добавлено в вишлист 📌" if cafe.is_wishlist else "убрано из вишлиста"
        await callback.answer(f"{cafe.name} {status}")
    else:
        await callback.answer("Не найдено", show_alert=True)


# ---- Удалить кафе ----

@router.callback_query(F.data.startswith("cafe:del:"))
async def cb_delete_cafe(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return

    cafe_id = int(callback.data.split(":")[2])
    if await delete_cafe(session, cafe_id):
        await callback.answer("Удалено")
        await callback.message.answer("🗑 Кафе удалено.", reply_markup=_back_cafe_kb().as_markup())
    else:
        await callback.answer("Не найдено", show_alert=True)


# ---- История визитов ----

@router.callback_query(F.data.startswith("cafe:vis:"))
async def cb_visits(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    page = int(callback.data.split(":")[2])
    page_size = 10
    visits = await list_visits(session, user.id, limit=page_size + 1, offset=page * page_size)
    has_more = len(visits) > page_size
    visits = visits[:page_size]

    if not visits:
        await callback.message.answer(
            "📜 <b>Визиты</b>\n\nПока нет записей.",
            reply_markup=_back_cafe_kb().as_markup(),
        )
        return

    lines = ["📜 <b>Последние визиты</b>\n"]
    for v in visits:
        d = v.visit_date.strftime("%d.%m")
        name = v.cafe.name if v.cafe else "?"
        r = f" ⭐{v.rating}" if v.rating else ""
        s = f" {fmt_money(v.spent)}" if v.spent else ""
        dish = f" — {v.dish}" if v.dish else ""
        lines.append(f"{d}  ☕ {esc(name)}{r}{s}{dish}")

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️ Новее", callback_data=f"cafe:vis:{page - 1}")
    if has_more:
        kb.button(text="➡️ Ранее", callback_data=f"cafe:vis:{page + 1}")
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    kb.adjust(nav, 2) if nav else kb.adjust(2)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Добавить кафе ----

@router.callback_query(F.data == "cafe:add")
async def cb_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CafeFlow.add_name)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    await callback.message.answer(
        "➕ <b>Новое кафе</b>\n\nВведи название:",
        reply_markup=kb.as_markup(),
    )


@router.message(CafeFlow.add_name)
async def process_add_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:128]
    if not name:
        await message.answer("Введи название.")
        return
    await state.update_data(cafe_name=name)
    await state.set_state(CafeFlow.add_address)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="cafe:addr:skip")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(1, 1)
    await message.answer(
        f"☕ <b>{esc(name)}</b>\n\nВведи адрес (или пропусти):",
        reply_markup=kb.as_markup(),
    )


@router.message(CafeFlow.add_address)
async def process_add_address(message: Message, state: FSMContext) -> None:
    addr = message.text.strip()[:256]
    await state.update_data(cafe_address=addr if addr else None)
    await _show_cuisine_picker(message, state)


@router.callback_query(F.data == "cafe:addr:skip")
async def cb_addr_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(cafe_address=None)
    await _show_cuisine_picker(callback.message, state)


async def _show_cuisine_picker(target: Message, state: FSMContext) -> None:
    await state.set_state(None)
    kb = InlineKeyboardBuilder()
    for emoji, name in CUISINE_TYPES:
        cb_name = name[:20]
        kb.button(text=f"{emoji} {name}", callback_data=f"cafe:cui:{cb_name}")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(3, 3, 3, 3, 1)
    await target.answer("Тип кухни:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cafe:cui:"))
async def cb_cuisine_selected(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    cuisine = callback.data.split(":", 2)[2]
    data = await state.get_data()
    name = data.get("cafe_name")
    if not name:
        await callback.answer("Сессия устарела", show_alert=True)
        await state.clear()
        return

    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 В вишлист", callback_data="cafe:savewl")
    kb.button(text="✅ Сохранить", callback_data="cafe:savenow")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(2, 1)

    await state.update_data(cafe_cuisine=cuisine)
    await callback.message.answer(
        f"☕ <b>{esc(name)}</b>\n🍽 {cuisine}\n\nСохранить или в вишлист?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.in_({"cafe:savewl", "cafe:savenow"}))
async def cb_save_cafe(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    name = data.get("cafe_name")
    if not name:
        await callback.answer("Сессия устарела", show_alert=True)
        await state.clear()
        return

    is_wl = callback.data == "cafe:savewl"
    cafe = await add_cafe(
        session,
        user.id,
        name=name,
        address=data.get("cafe_address"),
        cuisine=data.get("cafe_cuisine"),
        is_wishlist=is_wl,
    )
    await state.clear()
    await callback.answer()

    status = "📌 В вишлисте" if is_wl else "✅ Добавлено"
    await callback.message.answer(
        f"{status}: <b>{esc(name)}</b>",
        reply_markup=_back_cafe_kb().as_markup(),
    )


# ---- Логировать визит (выбор кафе) ----

@router.callback_query(F.data == "cafe:logpick")
async def cb_log_pick(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    cafes = await list_cafes(session, user.id)
    if not cafes:
        await callback.message.answer(
            "Сначала добавь кафе.", reply_markup=_back_cafe_kb().as_markup()
        )
        return

    kb = InlineKeyboardBuilder()
    for cafe in cafes[:15]:
        kb.button(text=f"☕ {cafe.name[:25]}", callback_data=f"cafe:log:{cafe.id}")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(1)
    await callback.message.answer("Где был?", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cafe:log:"))
async def cb_log_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    cafe_id = int(callback.data.split(":")[2])
    await state.update_data(visit_cafe_id=cafe_id)
    await state.set_state(CafeFlow.visit_rating)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    for i in range(1, 11):
        kb.button(text=str(i), callback_data=f"cafe:r:{i}")
    kb.button(text="Пропустить", callback_data="cafe:r:skip")
    kb.adjust(5, 5, 1)
    await callback.message.answer("⭐ Оценка от 1 до 10:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cafe:r:"))
async def cb_log_rating(callback: CallbackQuery, state: FSMContext) -> None:
    val = callback.data.split(":")[2]
    rating = int(val) if val != "skip" else None
    await state.update_data(visit_rating=rating)
    await state.set_state(CafeFlow.visit_spent)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="cafe:sp:skip")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(1, 1)
    await callback.message.answer(
        "💸 Сколько потратил? (число в рублях или пропусти)",
        reply_markup=kb.as_markup(),
    )


@router.message(CafeFlow.visit_spent)
async def process_visit_spent(message: Message, state: FSMContext) -> None:
    text = message.text.strip().replace(",", ".").replace("₽", "").replace("р", "").strip()
    try:
        spent = float(text)
    except ValueError:
        await message.answer("Введи число, например: <code>1500</code>")
        return
    await state.update_data(visit_spent=spent)
    await _ask_dish(message, state)


@router.callback_query(F.data == "cafe:sp:skip")
async def cb_spent_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(visit_spent=None)
    await callback.answer()
    await _ask_dish(callback.message, state)


async def _ask_dish(target: Message, state: FSMContext) -> None:
    await state.set_state(CafeFlow.visit_dish)
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="cafe:dish:skip")
    kb.button(text="❌ Отмена", callback_data="cafe:menu")
    kb.adjust(1, 1)
    await target.answer(
        "🍽 Что заказал? (коротко, или пропусти)",
        reply_markup=kb.as_markup(),
    )


@router.message(CafeFlow.visit_dish)
async def process_visit_dish(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    dish = message.text.strip()[:256]
    await state.update_data(visit_dish=dish if dish else None)
    await _save_visit(message, session, user, state)


@router.callback_query(F.data == "cafe:dish:skip")
async def cb_dish_skip(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.update_data(visit_dish=None)
    await callback.answer()
    await _save_visit(callback.message, session, user, state)


async def _save_visit(
    target: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    cafe_id = data.get("visit_cafe_id")
    if not cafe_id:
        await target.answer("Ошибка: кафе не выбрано.", reply_markup=_back_cafe_kb().as_markup())
        await state.clear()
        return

    today = user_today(user)
    visit = await add_visit(
        session,
        cafe_id=cafe_id,
        user_id=user.id,
        visit_date=today,
        rating=data.get("visit_rating"),
        spent=data.get("visit_spent"),
        dish=data.get("visit_dish"),
    )
    await state.clear()

    cafe = await get_cafe(session, cafe_id)
    name = cafe.name if cafe else "?"
    parts = [f"✅ Визит записан: <b>{esc(name)}</b>"]
    if visit.rating:
        parts.append(f"⭐ {visit.rating}/10")
    if visit.spent:
        parts.append(f"💸 {fmt_money(visit.spent)}")
    if visit.dish:
        parts.append(f"🍽 {esc(visit.dish)}")

    await target.answer("\n".join(parts), reply_markup=_back_cafe_kb().as_markup())
