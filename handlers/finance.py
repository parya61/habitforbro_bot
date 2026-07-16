"""Финансовый менеджер: доходы, расходы, сводка, автокатегоризация."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import User
from keyboards.nav import home_kb
from services.finance import MONTH_NAMES, ensure_seeded, fmt_money, parse_amount_merchant
from states import FinanceFlow
from utils import esc, user_today

router = Router()

ADMIN_TG_ID = config.admin_id


# ---- Клавиатуры ----

def _finance_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="➖ Расход", callback_data="fin:exp")
    kb.button(text="➕ Доход", callback_data="fin:inc")
    kb.button(text="📊 Сводка", callback_data="fin:sum")
    kb.button(text="📜 История", callback_data="fin:his:0")
    kb.button(text="📥 Импорт", callback_data="fin:import")
    kb.button(text="🛒 Продукты", callback_data="groc:menu")
    kb.button(text="☕ Кафе", callback_data="cafe:menu")
    kb.button(text="🎁 Подарки", callback_data="gift:menu")
    kb.button(text="✈️ Поездки", callback_data="trip:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 2, 1, 2, 2, 1)
    return kb


def _back_finance_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    return kb


# ---- Меню ----

async def _show_finance_menu(target: Message, session: AsyncSession, user: User) -> None:
    from db.finance_queries import monthly_totals

    today = user_today(user)
    month = f"{today.year}-{today.month:02d}"
    month_name = MONTH_NAMES[today.month]
    income, expenses = await monthly_totals(session, user.id, month)

    if income or expenses:
        balance = income - expenses
        sign = "+" if balance >= 0 else ""
        text = (
            f"💰 <b>Финансы — {month_name} {today.year}</b>\n\n"
            f"Доходы:  <b>+{fmt_money(income)}</b>\n"
            f"Расходы: <b>−{fmt_money(expenses)}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Баланс:  <b>{sign}{fmt_money(abs(balance))}</b>"
        )
    else:
        text = "💰 <b>Финансы</b>\n\nДобавь первую запись — расход или доход."

    await target.answer(text, reply_markup=_finance_menu_kb().as_markup())


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


@router.message(Command("finance"))
@router.message(F.text == "💰 Финансы")
async def cmd_finance(
    message: Message, session: AsyncSession, user: User
) -> None:
    if not _is_admin(user):
        await message.answer("Этот раздел пока недоступен.", reply_markup=home_kb())
        return
    await ensure_seeded(session, user.id)
    await _show_finance_menu(message, session, user)


@router.callback_query(F.data == "fin:menu")
async def cb_finance_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await _show_finance_menu(callback.message, session, user)


# ---- Добавление расхода ----

@router.callback_query(F.data == "fin:exp")
async def start_expense(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(FinanceFlow.expense_input)
    await state.update_data(tx_type="expense")
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="fin:menu")
    await callback.message.answer(
        "💸 <b>Новый расход</b>\n\n"
        "Введи сумму и описание:\n"
        "<code>1500 Пятёрочка</code>\n"
        "<code>450 кафе</code>\n"
        "<code>2200</code> (выберешь категорию)",
        reply_markup=kb.as_markup(),
    )


@router.message(FinanceFlow.expense_input)
async def process_expense(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    amount, merchant = parse_amount_merchant(message.text)
    if amount is None:
        await message.answer(
            "Не разобрал сумму. Попробуй: <code>1500 Пятёрочка</code>"
        )
        return

    await state.update_data(amount=amount, merchant=merchant)

    if merchant:
        from db.finance_queries import match_merchant

        cat = await match_merchant(session, user.id, merchant)
        if cat:
            await state.update_data(
                category_id=cat.id, cat_icon=cat.icon, cat_name=cat.name
            )
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Сохранить", callback_data="fin:save")
            kb.button(text="✏️ Категория", callback_data="fin:chcat")
            kb.button(text="❌ Отмена", callback_data="fin:menu")
            kb.adjust(2, 1)
            await message.answer(
                f"💸 <b>{fmt_money(amount)}</b> — {cat.icon} {esc(cat.name)}\n"
                f"📝 {esc(merchant)}\n\n"
                f"Всё верно?",
                reply_markup=kb.as_markup(),
            )
            return

    await _show_category_picker(message, session, user.id, "expense")


# ---- Добавление дохода ----

@router.callback_query(F.data == "fin:inc")
async def start_income(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(FinanceFlow.income_input)
    await state.update_data(tx_type="income")
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="fin:menu")
    await callback.message.answer(
        "💰 <b>Новый доход</b>\n\n" "Введи сумму:\n" "<code>113500</code>",
        reply_markup=kb.as_markup(),
    )


@router.message(FinanceFlow.income_input)
async def process_income(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    amount, merchant = parse_amount_merchant(message.text)
    if amount is None:
        await message.answer("Не разобрал сумму. Введи число: <code>113500</code>")
        return

    await state.update_data(amount=amount, merchant=merchant)
    await _show_category_picker(message, session, user.id, "income")


# ---- Выбор категории ----

async def _show_category_picker(
    target: Message, session: AsyncSession, user_id: int, cat_type: str
) -> None:
    from db.finance_queries import get_categories

    cats = await get_categories(session, user_id, cat_type)
    kb = InlineKeyboardBuilder()
    for cat in cats:
        kb.button(text=f"{cat.icon} {cat.name}", callback_data=f"fin:cat:{cat.id}")
    kb.button(text="❌ Отмена", callback_data="fin:menu")
    kb.adjust(2)

    label = "расхода" if cat_type == "expense" else "дохода"
    await target.answer(
        f"Выбери категорию {label}:", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("fin:cat:"))
async def category_selected(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    cat_id = int(callback.data.split(":")[2])
    data = await state.get_data()

    if not data.get("amount"):
        await callback.answer("Сессия устарела, начни заново.", show_alert=True)
        await state.clear()
        return

    from db.finance_queries import get_category

    cat = await get_category(session, cat_id)
    if not cat:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await state.update_data(
        category_id=cat.id, cat_icon=cat.icon, cat_name=cat.name
    )
    await callback.answer()
    await _save_transaction(callback.message, session, user, state)


@router.callback_query(F.data == "fin:chcat")
async def change_category(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    tx_type = data.get("tx_type", "expense")
    await callback.answer()
    await _show_category_picker(callback.message, session, user.id, tx_type)


# ---- Сохранение ----

@router.callback_query(F.data == "fin:save")
async def save_callback(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await callback.answer()
    await _save_transaction(callback.message, session, user, state)


async def _save_transaction(
    target: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    amount = data.get("amount")
    tx_type = data.get("tx_type", "expense")
    category_id = data.get("category_id")
    merchant = data.get("merchant")
    cat_icon = data.get("cat_icon", "")
    cat_name = data.get("cat_name", "")

    if not amount:
        await target.answer("Ошибка: нет суммы.", reply_markup=home_kb())
        await state.clear()
        return

    from db.finance_queries import add_transaction, learn_merchant

    today = user_today(user)

    await add_transaction(
        session,
        user_id=user.id,
        amount=amount,
        tx_type=tx_type,
        category_id=category_id,
        merchant=merchant,
        account="debit",
        tx_date=today,
    )

    if merchant and category_id:
        await learn_merchant(session, user.id, merchant, category_id)

    await state.clear()

    sign = "+" if tx_type == "income" else "−"
    desc = f" ({esc(merchant)})" if merchant else ""
    await target.answer(
        f"✅ Записано: {sign}{fmt_money(amount)} — {cat_icon} {esc(cat_name)}{desc}"
    )
    await _show_finance_menu(target, session, user)


# ---- Импорт PDF/CSV из Т-Банка ----

@router.callback_query(F.data == "fin:import")
async def start_import(
    callback: CallbackQuery, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.set_state(FinanceFlow.csv_upload)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="fin:menu")
    await callback.message.answer(
        "📥 <b>Импорт из Т-Банка</b>\n\n"
        "Отправь PDF-выписку или CSV-файл.\n\n"
        "Т-Банк → Главная → Счёт → Выписка → Скачать PDF",
        reply_markup=kb.as_markup(),
    )


@router.message(FinanceFlow.csv_upload, F.document)
async def process_import_file(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    doc = message.document
    fname = (doc.file_name or "").lower()

    if not (fname.endswith(".pdf") or fname.endswith(".csv")):
        await message.answer(
            "Пришли файл в формате PDF или CSV.\n"
            "Другие форматы не поддерживаются."
        )
        return

    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await message.answer("Файл слишком большой (макс 10 МБ).")
        return

    status_msg = await message.answer("⏳ Скачиваю и разбираю файл…")

    from aiogram import Bot

    bot: Bot = message.bot
    file = await bot.download(doc)
    raw = file.read()

    from services.csv_import import (
        ImportResult,
        format_import_summary,
        parse_tbank_csv,
        parse_tbank_pdf,
    )

    if fname.endswith(".pdf"):
        rows, parse_errors = parse_tbank_pdf(raw)
    else:
        rows, parse_errors = parse_tbank_csv(raw)

    if parse_errors and not rows:
        await state.clear()
        error_text = "\n".join(parse_errors[:5])
        await status_msg.edit_text(
            f"❌ <b>Не удалось разобрать файл</b>\n\n{error_text}",
            reply_markup=_back_finance_kb().as_markup(),
        )
        return

    if not rows:
        await state.clear()
        await status_msg.edit_text(
            "📭 В файле не найдено операций.",
            reply_markup=_back_finance_kb().as_markup(),
        )
        return

    from db.finance_queries import (
        check_duplicate,
        get_category_by_name,
        match_merchant,
    )
    from db.models import FinTransaction
    from services.finance import ensure_seeded

    await ensure_seeded(session, user.id)

    result = ImportResult()
    cat_cache: dict[tuple[str, str], int | None] = {}
    to_add: list[FinTransaction] = []

    for row in rows:
        is_dup = await check_duplicate(
            session, user.id, row.tx_date, row.amount, row.merchant, row.tx_type
        )
        if is_dup:
            result.skipped_dup += 1
            continue

        cache_key = (row.our_category, row.tx_type)
        if cache_key not in cat_cache:
            cat = await get_category_by_name(
                session, user.id, row.our_category, row.tx_type
            )
            cat_cache[cache_key] = cat.id if cat else None

        category_id = cat_cache[cache_key]

        if category_id is None:
            merchant_cat = await match_merchant(session, user.id, row.merchant)
            if merchant_cat:
                category_id = merchant_cat.id

        tx = FinTransaction(
            user_id=user.id,
            amount=row.amount,
            tx_type=row.tx_type,
            category_id=category_id,
            merchant=row.merchant or None,
            account="debit",
            tx_date=row.tx_date,
        )
        to_add.append(tx)

        cat_label = row.our_category
        result.cat_summary[cat_label] = result.cat_summary.get(cat_label, 0) + 1

        if result.date_min is None or row.tx_date < result.date_min:
            result.date_min = row.tx_date
        if result.date_max is None or row.tx_date > result.date_max:
            result.date_max = row.tx_date

    if to_add:
        from db.finance_queries import bulk_add_transactions
        await bulk_add_transactions(session, to_add)

    result.imported = len(to_add)
    result.errors = len(parse_errors)

    await state.clear()
    summary = format_import_summary(result)
    await status_msg.edit_text(summary, reply_markup=_back_finance_kb().as_markup())


@router.message(FinanceFlow.csv_upload)
async def import_not_document(message: Message) -> None:
    await message.answer(
        "Отправь PDF или CSV файл как документ (скрепка 📎)."
    )


# ---- Сводка за месяц ----

@router.callback_query(F.data == "fin:sum")
async def show_summary(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    from db.finance_queries import category_totals, monthly_totals

    await callback.answer()

    today = user_today(user)
    month = f"{today.year}-{today.month:02d}"
    month_name = MONTH_NAMES[today.month]
    income, expenses = await monthly_totals(session, user.id, month)

    if not income and not expenses:
        await callback.message.answer(
            f"📊 <b>{month_name.capitalize()} {today.year}</b>\n\n"
            f"Пока нет записей за этот месяц.",
            reply_markup=_back_finance_kb().as_markup(),
        )
        return

    balance = income - expenses
    sign = "+" if balance >= 0 else ""
    text = (
        f"📊 <b>{month_name.capitalize()} {today.year}</b>\n\n"
        f"💰 Доходы:  <b>+{fmt_money(income)}</b>\n"
        f"💸 Расходы: <b>−{fmt_money(expenses)}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 Баланс:  <b>{sign}{fmt_money(abs(balance))}</b>\n"
    )

    cats = await category_totals(session, user.id, month, "expense")
    if cats:
        text += "\n<b>По категориям:</b>\n"
        for icon, name, total in cats:
            pct = int(total / expenses * 100) if expenses > 0 else 0
            text += f"{icon} {esc(name)}  <b>{fmt_money(total)}</b>  {pct}%\n"

    await callback.message.answer(
        text, reply_markup=_back_finance_kb().as_markup()
    )


# ---- История ----

@router.callback_query(F.data.startswith("fin:his:"))
async def show_history(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    page = int(callback.data.split(":")[2])
    page_size = 10

    from db.finance_queries import list_transactions

    txs = await list_transactions(
        session, user.id, limit=page_size + 1, offset=page * page_size
    )
    has_more = len(txs) > page_size
    txs = txs[:page_size]

    await callback.answer()

    if not txs:
        await callback.message.answer(
            "📜 <b>История</b>\n\nПока нет записей.",
            reply_markup=_back_finance_kb().as_markup(),
        )
        return

    lines = ["📜 <b>Последние операции</b>\n"]
    for tx in txs:
        d = tx.tx_date.strftime("%d.%m")
        sign = "+" if tx.tx_type == "income" else "−"
        icon = tx.category.icon if tx.category else "📌"
        desc = tx.merchant or (tx.category.name if tx.category else "")
        lines.append(f"{d}  {sign}{fmt_money(tx.amount)}  {icon} {esc(desc)}")

    text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️ Новее", callback_data=f"fin:his:{page - 1}")
    if has_more:
        kb.button(text="➡️ Ранее", callback_data=f"fin:his:{page + 1}")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    kb.adjust(nav, 2) if nav else kb.adjust(2)

    await callback.message.answer(text, reply_markup=kb.as_markup())
