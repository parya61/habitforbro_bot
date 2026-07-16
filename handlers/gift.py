"""Gift handler: people, gift ideas, upcoming events."""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.gift_queries import (
    add_gift,
    add_person,
    count_persons,
    delete_gift,
    delete_person,
    get_gift,
    get_person,
    list_all_ideas,
    list_gifts_for_person,
    list_persons,
    update_gift_status,
)
from db.models import User
from services.finance import fmt_money
from services.gift import (
    GIFT_STATUSES,
    REL_LABELS,
    RELATIONSHIPS,
    days_label,
    upcoming_birthdays,
    upcoming_holidays,
)
from states import GiftFlow
from utils import esc, user_today

router = Router()

ADMIN_TG_ID = config.admin_id


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


# ---- Клавиатуры ----

def _gift_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Ближайшие", callback_data="gift:upcoming")
    kb.button(text="💡 Идеи", callback_data="gift:ideas")
    kb.button(text="👥 Люди", callback_data="gift:people:0")
    kb.button(text="➕ Человек", callback_data="gift:addp")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 2, 2)
    return kb


def _back_gift_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


# ---- Меню ----

@router.callback_query(F.data == "gift:menu")
async def cb_gift_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()

    persons = await list_persons(session, user.id)
    today = user_today(user)
    bdays = upcoming_birthdays(persons, today)
    holidays = upcoming_holidays(today)
    ideas = await list_all_ideas(session, user.id)

    text = (
        f"🎁 <b>Подарки</b>\n\n"
        f"Людей: {len(persons)}\n"
        f"Идей подарков: {len(ideas)}\n"
        f"Ближайших событий: {len(bdays) + len(holidays)}"
    )
    await callback.message.answer(text, reply_markup=_gift_menu_kb().as_markup())


# ---- Ближайшие события ----

@router.callback_query(F.data == "gift:upcoming")
async def cb_upcoming(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    today = user_today(user)
    persons = await list_persons(session, user.id)
    bdays = upcoming_birthdays(persons, today, days_ahead=60)
    holidays = upcoming_holidays(today, days_ahead=60)

    lines = ["📅 <b>Ближайшие события</b> (60 дней)\n"]

    if not bdays and not holidays:
        lines.append("Пока ничего не предвидится.")
    else:
        for hdate, hname, delta in holidays:
            d = hdate.strftime("%d.%m")
            lines.append(f"{hname} — {d} ({days_label(delta)})")

        if bdays:
            lines.append("")
            for person, bdate, delta, age in bdays:
                d = bdate.strftime("%d.%m")
                rel = REL_LABELS.get(person.rel_type, "")
                rel_str = f" ({rel})" if rel else ""
                gifts = person.gifts or []
                ideas = [g for g in gifts if g.status == "idea"]
                gift_hint = f" — 💡{len(ideas)} идей" if ideas else ""
                lines.append(
                    f"🎂 <b>{esc(person.name)}</b>{rel_str} — {d}, {age} лет "
                    f"({days_label(delta)}){gift_hint}"
                )

    await callback.message.answer(
        "\n".join(lines), reply_markup=_back_gift_kb().as_markup()
    )


# ---- Все идеи ----

@router.callback_query(F.data == "gift:ideas")
async def cb_ideas(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    ideas = await list_all_ideas(session, user.id)
    if not ideas:
        await callback.message.answer(
            "💡 <b>Идеи подарков</b>\n\nПока пусто. Добавь идею через карточку человека.",
            reply_markup=_back_gift_kb().as_markup(),
        )
        return

    lines = [f"💡 <b>Идеи подарков</b> ({len(ideas)})\n"]
    for g in ideas[:20]:
        person_name = g.person.name if g.person else "?"
        price = f" ~{fmt_money(g.price_estimate)}" if g.price_estimate else ""
        lines.append(f"🎁 {esc(g.title)}{price} → {esc(person_name)}")

    kb = InlineKeyboardBuilder()
    for g in ideas[:8]:
        kb.button(text=f"✏️ {g.title[:20]}", callback_data=f"gift:gi:{g.id}")
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    rows = [1] * min(len(ideas), 8) + [2]
    kb.adjust(*rows)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Список людей ----

@router.callback_query(F.data.startswith("gift:people:"))
async def cb_people(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    page = int(callback.data.split(":")[2])
    page_size = 10
    persons = await list_persons(session, user.id)
    total = len(persons)
    start = page * page_size
    page_persons = persons[start : start + page_size]
    has_more = start + page_size < total

    if not persons:
        await callback.message.answer(
            "👥 <b>Люди</b>\n\nПока никого. Добавь первого человека.",
            reply_markup=_back_gift_kb().as_markup(),
        )
        return

    lines = [f"👥 <b>Люди</b> ({total})\n"]
    for p in page_persons:
        rel = REL_LABELS.get(p.rel_type, "")
        rel_str = f" ({rel})" if rel else ""
        bday = f" 🎂{p.birthday.strftime('%d.%m')}" if p.birthday else ""
        gifts_count = len(p.gifts) if p.gifts else 0
        g = f" — 🎁{gifts_count}" if gifts_count else ""
        lines.append(f"👤 {esc(p.name)}{rel_str}{bday}{g}")

    kb = InlineKeyboardBuilder()
    for p in page_persons[:8]:
        kb.button(text=f"👤 {p.name[:20]}", callback_data=f"gift:vp:{p.id}")
    if page > 0:
        kb.button(text="⬅️", callback_data=f"gift:people:{page - 1}")
    if has_more:
        kb.button(text="➡️", callback_data=f"gift:people:{page + 1}")
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    person_rows = [1] * min(len(page_persons), 8)
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    if nav:
        person_rows.append(nav)
    person_rows.append(2)
    kb.adjust(*person_rows)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Карточка человека ----

@router.callback_query(F.data.startswith("gift:vp:"))
async def cb_view_person(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    person_id = int(callback.data.split(":")[2])
    person = await get_person(session, person_id)
    if not person:
        await callback.message.answer("Не найден.", reply_markup=_back_gift_kb().as_markup())
        return

    rel = REL_LABELS.get(person.rel_type, "")
    lines = [f"👤 <b>{esc(person.name)}</b>"]
    if rel:
        lines.append(f"👥 {rel}")
    if person.birthday:
        lines.append(f"🎂 {person.birthday.strftime('%d.%m.%Y')}")
    if person.notes:
        lines.append(f"📝 {esc(person.notes)}")

    gifts = person.gifts or []
    if gifts:
        lines.append(f"\n<b>Подарки:</b>")
        for g in gifts:
            status = GIFT_STATUSES.get(g.status, g.status)
            price = f" ~{fmt_money(g.price_estimate)}" if g.price_estimate else ""
            lines.append(f"  {status} {esc(g.title)}{price}")

    kb = InlineKeyboardBuilder()
    kb.button(text="💡 Добавить идею", callback_data=f"gift:ag:{person_id}")
    for g in gifts[:6]:
        if g.status == "idea":
            kb.button(text=f"🛍 {g.title[:18]}", callback_data=f"gift:buy:{g.id}")
        elif g.status == "bought":
            kb.button(text=f"🎁 {g.title[:18]}", callback_data=f"gift:give:{g.id}")
    kb.button(text="🗑 Удалить", callback_data=f"gift:delp:{person_id}")
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.adjust(1, *([1] * min(len([g for g in gifts if g.status in ("idea", "bought")]), 6)), 1, 1)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


# ---- Добавить человека ----

@router.callback_query(F.data == "gift:addp")
async def cb_add_person(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(GiftFlow.person_name)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="gift:menu")
    await callback.message.answer(
        "👤 <b>Новый человек</b>\n\nВведи имя:",
        reply_markup=kb.as_markup(),
    )


@router.message(GiftFlow.person_name)
async def process_person_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:128]
    if not name:
        await message.answer("Введи имя.")
        return
    await state.update_data(person_name=name)
    await state.set_state(GiftFlow.person_bday)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="gift:bday:skip")
    kb.button(text="❌ Отмена", callback_data="gift:menu")
    kb.adjust(1, 1)
    await message.answer(
        f"👤 <b>{esc(name)}</b>\n\n"
        "Дата рождения? (ДД.ММ.ГГГГ или ДД.ММ)",
        reply_markup=kb.as_markup(),
    )


@router.message(GiftFlow.person_bday)
async def process_person_bday(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    bday = _parse_date(text)
    if bday is None:
        await message.answer("Формат: <code>15.03.1990</code> или <code>15.03</code>")
        return
    await state.update_data(person_bday=bday.isoformat())
    await _show_rel_picker(message)


@router.callback_query(F.data == "gift:bday:skip")
async def cb_bday_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(person_bday=None)
    await callback.answer()
    await _show_rel_picker(callback.message)


async def _show_rel_picker(target: Message) -> None:
    kb = InlineKeyboardBuilder()
    for code, label in RELATIONSHIPS:
        kb.button(text=label, callback_data=f"gift:rel:{code}")
    kb.button(text="❌ Отмена", callback_data="gift:menu")
    kb.adjust(3, 3, 3, 1)
    await target.answer("Кто этот человек?", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("gift:rel:"))
async def cb_rel_selected(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    rel = callback.data.split(":")[2]
    data = await state.get_data()
    name = data.get("person_name")
    if not name:
        await callback.answer("Сессия устарела", show_alert=True)
        await state.clear()
        return

    bday_str = data.get("person_bday")
    from datetime import date as date_cls
    bday = date_cls.fromisoformat(bday_str) if bday_str else None

    person = await add_person(session, user.id, name, bday, rel_type=rel)
    await state.clear()
    await callback.answer()

    rel_label = REL_LABELS.get(rel, "")
    bday_text = f"\n🎂 {bday.strftime('%d.%m.%Y')}" if bday else ""
    await callback.message.answer(
        f"✅ Добавлен: <b>{esc(name)}</b> ({rel_label}){bday_text}",
        reply_markup=_back_gift_kb().as_markup(),
    )


# ---- Удалить человека ----

@router.callback_query(F.data.startswith("gift:delp:"))
async def cb_delete_person(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    person_id = int(callback.data.split(":")[2])
    if await delete_person(session, person_id):
        await callback.answer("Удалён")
        await callback.message.answer("🗑 Удалено.", reply_markup=_back_gift_kb().as_markup())
    else:
        await callback.answer("Не найден", show_alert=True)


# ---- Добавить идею подарка ----

@router.callback_query(F.data.startswith("gift:ag:"))
async def cb_add_gift_start(callback: CallbackQuery, state: FSMContext) -> None:
    person_id = int(callback.data.split(":")[2])
    await state.update_data(gift_person_id=person_id)
    await state.set_state(GiftFlow.gift_title)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="gift:menu")
    await callback.message.answer(
        "💡 <b>Идея подарка</b>\n\nЧто подарить? Введи название:",
        reply_markup=kb.as_markup(),
    )


@router.message(GiftFlow.gift_title)
async def process_gift_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()[:256]
    if not title:
        await message.answer("Введи название подарка.")
        return
    await state.update_data(gift_title=title)
    await state.set_state(GiftFlow.gift_price)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="gift:price:skip")
    kb.button(text="❌ Отмена", callback_data="gift:menu")
    kb.adjust(1, 1)
    await message.answer(
        f"🎁 <b>{esc(title)}</b>\n\nПримерная цена? (число или пропусти)",
        reply_markup=kb.as_markup(),
    )


@router.message(GiftFlow.gift_price)
async def process_gift_price(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    text = message.text.strip().replace(",", ".").replace("₽", "").replace("р", "").strip()
    try:
        price = float(text)
    except ValueError:
        await message.answer("Введи число, например: <code>3000</code>")
        return
    await state.update_data(gift_price=price)
    await _save_gift(message, session, user, state)


@router.callback_query(F.data == "gift:price:skip")
async def cb_price_skip(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.update_data(gift_price=None)
    await callback.answer()
    await _save_gift(callback.message, session, user, state)


async def _save_gift(
    target: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    person_id = data.get("gift_person_id")
    title = data.get("gift_title")
    price = data.get("gift_price")

    if not person_id or not title:
        await target.answer("Ошибка.", reply_markup=_back_gift_kb().as_markup())
        await state.clear()
        return

    gift = await add_gift(session, user.id, person_id, title, price)
    await state.clear()

    person = await get_person(session, person_id)
    pname = person.name if person else "?"
    price_str = f" ~{fmt_money(price)}" if price else ""
    await target.answer(
        f"✅ Идея: <b>{esc(title)}</b>{price_str}\n→ {esc(pname)}",
        reply_markup=_back_gift_kb().as_markup(),
    )


# ---- Купил / Подарил ----

@router.callback_query(F.data.startswith("gift:buy:"))
async def cb_mark_bought(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    gift_id = int(callback.data.split(":")[2])
    gift = await update_gift_status(session, gift_id, "bought")
    if gift:
        await callback.answer(f"🛍 {gift.title} — куплено!")
    else:
        await callback.answer("Не найдено", show_alert=True)


@router.callback_query(F.data.startswith("gift:give:"))
async def cb_mark_given(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    gift_id = int(callback.data.split(":")[2])
    today = user_today(user)
    gift = await update_gift_status(session, gift_id, "given", given_date=today)
    if gift:
        await callback.answer(f"🎁 {gift.title} — подарено!")
    else:
        await callback.answer("Не найдено", show_alert=True)


# ---- Карточка идеи ----

@router.callback_query(F.data.startswith("gift:gi:"))
async def cb_view_gift(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()

    gift_id = int(callback.data.split(":")[2])
    gift = await get_gift(session, gift_id)
    if not gift:
        await callback.message.answer("Не найдено.", reply_markup=_back_gift_kb().as_markup())
        return

    status = GIFT_STATUSES.get(gift.status, gift.status)
    lines = [f"🎁 <b>{esc(gift.title)}</b>"]
    lines.append(f"Статус: {status}")
    if gift.person:
        lines.append(f"Для: {esc(gift.person.name)}")
    if gift.price_estimate:
        lines.append(f"💰 ~{fmt_money(gift.price_estimate)}")

    kb = InlineKeyboardBuilder()
    if gift.status == "idea":
        kb.button(text="🛍 Купил", callback_data=f"gift:buy:{gift.id}")
    if gift.status == "bought":
        kb.button(text="🎁 Подарил", callback_data=f"gift:give:{gift.id}")
    kb.button(text="🗑 Удалить", callback_data=f"gift:delg:{gift.id}")
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.adjust(1, 1, 1)

    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("gift:delg:"))
async def cb_delete_gift(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    gift_id = int(callback.data.split(":")[2])
    if await delete_gift(session, gift_id):
        await callback.answer("Удалено")
        await callback.message.answer("🗑 Идея удалена.", reply_markup=_back_gift_kb().as_markup())
    else:
        await callback.answer("Не найдено", show_alert=True)


# ---- Helpers ----

def _parse_date(text: str):
    from datetime import date as date_cls
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            d = datetime.strptime(text, fmt).date()
            if d.year == 1900:
                d = d.replace(year=2000)
            return d
        except ValueError:
            continue
    return None
