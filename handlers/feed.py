"""Feed aggregator: manage Telegram & YouTube sources, view content."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from db.models import User
from keyboards.nav import home_kb
from states import FeedFlow
from utils import esc

router = Router()

ADMIN_TG_ID = config.admin_id


def _is_admin(user: User) -> bool:
    return user.telegram_id == ADMIN_TG_ID


def _feed_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📡 Мои источники", callback_data="feed:sources")
    kb.button(text="📰 Последнее", callback_data="feed:recent:0")
    kb.button(text="➕ Telegram-канал", callback_data="feed:add_tg")
    kb.button(text="➕ YouTube-канал", callback_data="feed:add_yt")
    kb.button(text="🔄 Обновить сейчас", callback_data="feed:refresh")
    kb.button(text="🔍 Поиск", callback_data="feed:search")
    kb.button(text="💰 Финансы", callback_data="fin:menu")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2, 2, 2, 2)
    return kb


# ---- Menu ----

async def show_feed_menu(target: Message, session: AsyncSession, user: User) -> None:
    from db.feed_queries import list_sources

    sources = await list_sources(session, user.id)
    tg_cnt = sum(1 for s in sources if s.source_type == "telegram")
    yt_cnt = sum(1 for s in sources if s.source_type == "youtube")

    if sources:
        text = (
            f"📡 <b>Сбор информации</b>\n\n"
            f"Telegram-каналов: <b>{tg_cnt}</b>\n"
            f"YouTube-каналов: <b>{yt_cnt}</b>"
        )
    else:
        text = (
            "📡 <b>Сбор информации</b>\n\n"
            "Пока нет источников. Добавь Telegram или YouTube каналы — "
            "Керя будет видеть свежий контент."
        )

    await target.answer(text, reply_markup=_feed_menu_kb().as_markup())


@router.callback_query(F.data == "feed:menu")
async def cb_feed_menu(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    if not _is_admin(user):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await show_feed_menu(callback.message, session, user)


# ---- List sources ----

@router.callback_query(F.data == "feed:sources")
async def list_sources_cb(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    from db.feed_queries import count_items_by_source, list_sources

    sources = await list_sources(session, user.id)
    await callback.answer()

    if not sources:
        await callback.message.answer(
            "Нет добавленных источников.",
            reply_markup=_feed_menu_kb().as_markup(),
        )
        return

    lines = ["📡 <b>Источники</b>\n"]
    for src in sources:
        cnt = await count_items_by_source(session, src.id)
        icon = "📢" if src.source_type == "telegram" else "🎬"
        status = "✅" if src.active else "⏸"
        lines.append(f"{status} {icon} <b>{esc(src.title)}</b> ({cnt} записей)")

    kb = InlineKeyboardBuilder()
    for src in sources:
        label = f"❌ {src.title[:25]}"
        kb.button(text=label, callback_data=f"feed:del:{src.id}")
    kb.button(text="⬅️ Назад", callback_data="feed:menu")
    kb.adjust(1)

    await callback.message.answer(
        "\n".join(lines), reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("feed:del:"))
async def delete_source_cb(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    src_id = int(callback.data.split(":")[2])
    from db.feed_queries import delete_source, get_source

    src = await get_source(session, src_id)
    if not src:
        await callback.answer("Источник не найден", show_alert=True)
        return

    name = src.title
    await delete_source(session, src_id)
    await callback.answer(f"Удалён: {name}")
    await show_feed_menu(callback.message, session, user)


# ---- Add Telegram ----

@router.callback_query(F.data == "feed:add_tg")
async def start_add_tg(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(FeedFlow.add_tg)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="feed:menu")
    await callback.message.answer(
        "📢 <b>Добавить Telegram-канал</b>\n\n"
        "Введи username канала (без @):\n"
        "<code>durov</code>\n"
        "<code>habr_com</code>",
        reply_markup=kb.as_markup(),
    )


@router.message(FeedFlow.add_tg)
async def process_add_tg(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    username = message.text.strip().lstrip("@").replace("https://t.me/", "")
    if not username or len(username) > 128:
        await message.answer("Неправильный username. Попробуй ещё раз.")
        return

    from db.feed_queries import add_source

    title = username
    try:
        from services.feed_telegram import resolve_channel_title
        resolved = await resolve_channel_title(username)
        if resolved:
            title = resolved
    except Exception:
        pass

    await add_source(session, user.id, "telegram", username, title)
    await state.clear()
    await message.answer(f"✅ Telegram-канал <b>{esc(title)}</b> добавлен!")
    await show_feed_menu(message, session, user)


# ---- Add YouTube ----

@router.callback_query(F.data == "feed:add_yt")
async def start_add_yt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(FeedFlow.add_yt)
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="feed:menu")
    await callback.message.answer(
        "🎬 <b>Добавить YouTube-канал</b>\n\n"
        "Введи channel ID или ссылку на канал:\n"
        "<code>UCxxxxxx</code>\n"
        "<code>https://youtube.com/channel/UCxxxxxx</code>\n\n"
        "Channel ID можно найти: канал → О канале → Поделиться → Копировать ID",
        reply_markup=kb.as_markup(),
    )


@router.message(FeedFlow.add_yt)
async def process_add_yt(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    from services.feed_youtube import extract_channel_id, fetch_channel_title

    raw = message.text.strip()
    channel_id = extract_channel_id(raw)

    if not channel_id:
        await message.answer(
            "Не удалось определить channel ID.\n"
            "Нужен формат UCxxxxxxxx или ссылка на канал."
        )
        return

    title = fetch_channel_title(channel_id) or channel_id

    from db.feed_queries import add_source

    await add_source(session, user.id, "youtube", channel_id, title)
    await state.clear()
    await message.answer(f"✅ YouTube-канал <b>{esc(title)}</b> добавлен!")
    await show_feed_menu(message, session, user)


# ---- Recent items ----

@router.callback_query(F.data.startswith("feed:recent:"))
async def show_recent(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    page = int(callback.data.split(":")[2])
    page_size = 8
    await callback.answer()

    from db.feed_queries import recent_items

    items = await recent_items(session, user.id, limit=page_size + 1)
    if page > 0:
        items = items[page * page_size : (page + 1) * page_size + 1]

    has_more = len(items) > page_size
    items = items[:page_size]

    if not items:
        await callback.message.answer(
            "📰 Пока нет собранного контента.\n"
            "Добавь источники и нажми 🔄 Обновить.",
            reply_markup=_feed_menu_kb().as_markup(),
        )
        return

    lines = ["📰 <b>Последний контент</b>\n"]
    for item in items:
        icon = "📢" if item.item_type == "post" else "🎬"
        title = (item.title or "")[:80]
        src_name = item.source.title if item.source else "?"
        date_str = item.published_at.strftime("%d.%m") if item.published_at else ""
        link = f"<a href='{item.url}'>{esc(title)}</a>" if item.url else esc(title)
        lines.append(f"{date_str} {icon} {link}\n     <i>{esc(src_name)}</i>")

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️ Новее", callback_data=f"feed:recent:{page - 1}")
    if has_more:
        kb.button(text="➡️ Ранее", callback_data=f"feed:recent:{page + 1}")
    kb.button(text="📡 Источники", callback_data="feed:menu")
    nav = (1 if page > 0 else 0) + (1 if has_more else 0)
    if nav:
        kb.adjust(nav, 1)
    else:
        kb.adjust(1)

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=kb.as_markup(),
        disable_web_page_preview=True,
    )


# ---- Refresh ----

@router.callback_query(F.data == "feed:refresh")
async def refresh_feeds(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    await callback.answer("Обновляю...")

    from services.feed_aggregator import run_feed_check

    msg = await callback.message.answer("⏳ Проверяю источники...")

    try:
        results = await run_feed_check(session, user.id)
    except Exception as exc:
        await msg.edit_text(f"❌ Ошибка: {exc}")
        return

    tg = results.get("telegram", 0)
    yt = results.get("youtube", 0)
    total = tg + yt

    if total:
        text = (
            f"✅ <b>Обновлено</b>\n\n"
            f"📢 Telegram: +{tg} постов\n"
            f"🎬 YouTube: +{yt} видео"
        )
    else:
        text = "✅ Нового контента нет."

    kb = InlineKeyboardBuilder()
    kb.button(text="📡 Источники", callback_data="feed:menu")
    await msg.edit_text(text, reply_markup=kb.as_markup())


# ---- Search ----

@router.callback_query(F.data == "feed:search")
async def start_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    from states import AnalyticsFlow
    # Reuse analytics chat — user asks Kerya, who sees feed context
    kb = InlineKeyboardBuilder()
    kb.button(text="📡 Назад", callback_data="feed:menu")
    await callback.message.answer(
        "🔍 <b>Поиск по контенту</b>\n\n"
        "Просто спроси Керю (🧠 Аналитика) — он видит весь собранный контент "
        "и может найти и проанализировать что нужно.",
        reply_markup=kb.as_markup(),
    )
