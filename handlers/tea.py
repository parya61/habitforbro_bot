"""Чайный дневник: профиль, запись чаепитий, лента, сообщения, статистика."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.queries import (
    add_tea_collection,
    add_tea_session,
    avg_tea_rating,
    count_tea_sessions,
    delete_tea_collection_item,
    delete_tea_session,
    get_random_tea,
    get_tea_collection_item,
    get_tea_profile,
    get_tea_session,
    get_user_by_tg,
    list_public_tea_sessions,
    list_tea_collection,
    list_tea_sessions,
    list_user_public_tea_sessions,
    list_users,
    subtract_tea_grams,
    tea_name_stats,
    tea_session_dates,
    tea_type_stats,
    update_tea_collection_item,
    update_tea_session,
    update_user_settings,
    upsert_tea_profile,
)
from keyboards.nav import home_kb
from states import (
    TeaCollEditFlow,
    TeaCollectionFlow,
    TeaEditFlow,
    TeaMessageFlow,
    TeaProfileFlow,
    TeaSessionFlow,
)
from utils import display_name, esc, user_today

router = Router()

# -- Константы --

TEA_TYPES = {
    "puer_shu": "шу пуэр",
    "puer_sheng": "шэн пуэр",
    "red": "красный",
    "oolong": "улун",
    "green": "зелёный",
    "white": "белый",
    "yellow": "жёлтый",
    "heicha": "хэй ча",
    "other": "другой",
}

TEA_TYPE_EMOJI = {
    "puer_shu": "🟤",
    "puer_sheng": "🟢",
    "red": "🔴",
    "oolong": "🔵",
    "green": "🍃",
    "white": "⚪",
    "yellow": "🟡",
    "heicha": "⚫",
    "other": "🍵",
}

TASTE_TAGS = [
    "маслянистый", "древесный", "цветочный", "фруктовый",
    "шоколадный", "ореховый", "медовый", "карамельный",
    "ягодный", "сухофруктовый", "хлебный", "дымный",
    "сливочный", "минеральный", "пряный", "камфорный",
    "кислинка", "сладость", "горчинка", "терпкость", "свежесть",
]

CHA_QI_OPTIONS = {
    "vigor": "⚡ бодрит",
    "relax": "😌 расслабляет",
    "warm": "🔥 согревает",
    "satiety": "🍽 сытость",
    "meditate": "🧘 медитативный",
    "none": "🤷 не заметил",
}


PAGE_SIZE = 5


def _trim_for_cb(prefix: str, text: str) -> str:
    while len((prefix + text).encode()) > 64:
        text = text[:-1]
    return text


def _tea_menu_kb(user: User | None = None) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍵 Записать чаепитие", callback_data="tea:write")
    kb.button(text="🌍 Чайная лента", callback_data="tea:feed:0")
    kb.button(text="📚 Мои записи", callback_data="tea:history")
    kb.button(text="🗄 Моя коллекция", callback_data="tc:list")
    kb.button(text="🎲 Что заварить?", callback_data="tc:random")
    kb.button(text="📊 Чайная статистика", callback_data="tea:stats")
    kb.button(text="👤 Мой чайный профиль", callback_data="tea:profile")
    if user is not None:
        priv = "🔒 Скрыть записи" if not user.tea_diary_private else "🔓 Открыть записи"
        kb.button(text=priv, callback_data="tea:toggle_privacy")
    kb.adjust(1)
    return kb


def _tea_type_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code, label in TEA_TYPES.items():
        emoji = TEA_TYPE_EMOJI[code]
        kb.button(text=f"{emoji} {label}", callback_data=f"tt:{code}")
    kb.button(text="✏️ Свой вид", callback_data="tt:custom")
    kb.adjust(3, 3, 3, 1)
    return kb


def _rating_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for i in range(1, 11):
        kb.button(text=str(i), callback_data=f"tr:{i}")
    kb.button(text="Пропустить", callback_data="tr:skip")
    kb.adjust(5, 5, 1)
    return kb


def _tags_kb(selected: set[str]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for tag in TASTE_TAGS:
        mark = "✅ " if tag in selected else ""
        cb = _trim_for_cb("ttag:", tag)
        kb.button(text=f"{mark}{tag}", callback_data=f"ttag:{cb}")
    custom = selected - set(TASTE_TAGS)
    for tag in sorted(custom):
        cb = _trim_for_cb("ttag:", tag)
        kb.button(text=f"✅ {tag}", callback_data=f"ttag:{cb}")
    kb.button(text="✏️ Свой тег", callback_data="ttag:custom")
    kb.button(text="✔️ Готово", callback_data="ttag:done")
    kb.button(text="Пропустить", callback_data="ttag:skip")
    total_tags = len(TASTE_TAGS) + len(custom)
    rows = [2] * (total_tags // 2) + ([1] if total_tags % 2 else [])
    rows += [1, 1, 1]
    kb.adjust(*rows)
    return kb


def _cha_qi_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code, label in CHA_QI_OPTIONS.items():
        kb.button(text=label, callback_data=f"tq:{code}")
    kb.button(text="Пропустить", callback_data="tq:skip")
    kb.adjust(2, 2, 2, 1)
    return kb


def _type_label(code: str) -> str:
    if code.startswith("custom:"):
        return f"🍵 {code[7:]}"
    emoji = TEA_TYPE_EMOJI.get(code, "🍵")
    name = TEA_TYPES.get(code, code)
    return f"{emoji} {name}"


# ==================== Главное меню ====================

@router.message(Command("tea"))
@router.message(F.text == "🍵 Чай")
async def cmd_tea(message: Message, user: User) -> None:
    await show_tea_menu(message, user)


async def show_tea_menu(message: Message, user: User | None = None) -> None:
    priv_hint = ""
    if user and user.tea_diary_private:
        priv_hint = "\n🔒 Твои записи скрыты от других."
    await message.answer(
        "🍵 <b>Чайный дневник</b>\n"
        f"Записывай чаепития, отслеживай вкусы и серии.{priv_hint}",
        reply_markup=_tea_menu_kb(user).as_markup(),
    )


# ==================== Чайный профиль ====================

@router.callback_query(F.data == "tea:profile")
async def tea_profile_view(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    profile = await get_tea_profile(session, user.id)
    if profile is None:
        await callback.message.answer(
            "👤 <b>Чайный профиль</b>\n\n"
            "Ты ещё не заполнил профиль. Расскажи о своём пути к чаю!",
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="✍️ Заполнить профиль", callback_data="tea:profile_start")
        kb.button(text="⬅️ Назад", callback_data="go:tea")
        kb.adjust(1)
        await callback.message.answer("Начнём?", reply_markup=kb.as_markup())
    else:
        lines = ["👤 <b>Мой чайный профиль</b>\n"]
        if profile.tea_story:
            lines.append(f"📖 <i>{esc(profile.tea_story)}</i>\n")
        if profile.favorite_types:
            types = [_type_label(t) for t in profile.favorite_types.split(",")]
            lines.append(f"❤️ Любимые: {', '.join(types)}")
        if profile.taste_preferences:
            lines.append(f"👅 Вкусы: {profile.taste_preferences}")
        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Редактировать", callback_data="tea:profile_start")
        kb.button(text="⬅️ Назад", callback_data="go:tea")
        kb.adjust(2)
        await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "tea:profile_start")
async def tea_profile_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaProfileFlow.story)
    await callback.message.answer(
        "📖 <b>Мой путь к чаю</b>\n\n"
        "Расскажи: как и когда ты пришёл к чаю? Что тебя привлекло?\n\n"
        "<i>Или напиши «пропустить».</i>"
    )
    await callback.answer()


def _profile_types_kb(selected: set[str]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for c, label in TEA_TYPES.items():
        emoji = TEA_TYPE_EMOJI[c]
        mark = "✅ " if c in selected else ""
        kb.button(text=f"{mark}{emoji} {label}", callback_data=f"tt:{c}")
    custom = {s for s in selected if s.startswith("custom:")}
    for c in sorted(custom):
        name = c[7:]
        cb = _trim_for_cb("tt:", c)
        kb.button(text=f"✅ 🍵 {name}", callback_data=f"tt:{cb}")
    kb.button(text="✏️ Свой вид", callback_data="tt:custom")
    kb.button(text="✔️ Готово", callback_data="tp:types_done")
    total = len(TEA_TYPES) + len(custom)
    rows = [3] * (total // 3) + ([total % 3] if total % 3 else [])
    rows += [1, 1]
    kb.adjust(*rows)
    return kb


@router.message(TeaProfileFlow.story)
async def tea_profile_story(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    story = None if text.lower() in ("пропустить", "skip", "-") else text
    await state.update_data(tea_story=story)
    await state.set_state(TeaProfileFlow.types)
    await message.answer(
        "❤️ <b>Любимые виды чая</b>\n\n"
        "Выбери один или несколько (нажимай, потом «Готово»):",
        reply_markup=_profile_types_kb(set()).as_markup(),
    )


@router.callback_query(F.data == "tt:custom", TeaProfileFlow.types)
async def tea_profile_type_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaProfileFlow.custom_type)
    await callback.message.answer(
        "✏️ Напиши свой вид чая (например: габа, жасминовый, бай му дань):"
    )
    await callback.answer()


@router.message(TeaProfileFlow.custom_type)
async def tea_profile_type_custom_text(message: Message, state: FSMContext) -> None:
    text = _trim_for_cb("tt:custom:", (message.text or "").strip())
    if not text:
        await message.answer("Введи название вида чая:")
        return
    code = f"custom:{text}"
    data = await state.get_data()
    selected = set(data.get("profile_types", "").split(",")) - {""}
    selected.add(code)
    await state.update_data(profile_types=",".join(selected))
    await state.set_state(TeaProfileFlow.types)
    await message.answer(
        f"✅ Вид «{esc(text)}» добавлен.\n\n"
        "❤️ Выбирай ещё или нажми «Готово»:",
        reply_markup=_profile_types_kb(selected).as_markup(),
    )


@router.callback_query(F.data.startswith("tt:"), TeaProfileFlow.types)
async def tea_profile_toggle_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data[3:]
    data = await state.get_data()
    selected = set(data.get("profile_types", "").split(",")) - {""}
    if code in selected:
        selected.discard(code)
    else:
        selected.add(code)
    await state.update_data(profile_types=",".join(selected))
    await callback.message.edit_reply_markup(reply_markup=_profile_types_kb(selected).as_markup())
    await callback.answer()


@router.callback_query(F.data == "tp:types_done", TeaProfileFlow.types)
async def tea_profile_types_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaProfileFlow.tastes)
    await state.update_data(profile_tastes=set())
    await callback.message.answer(
        "👅 <b>Вкусовые предпочтения</b>\n\n"
        "Что тебе нравится в чае? Выбери теги:",
        reply_markup=_tags_kb(set()).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ttag:"), TeaProfileFlow.tastes)
async def tea_profile_toggle_taste(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    tag = callback.data[5:]
    data = await state.get_data()

    if tag == "done" or tag == "skip":
        selected_tastes = data.get("profile_tastes", set())
        taste_str = ", ".join(sorted(selected_tastes)) if isinstance(selected_tastes, set) and selected_tastes else None
        await upsert_tea_profile(
            session,
            user.id,
            tea_story=data.get("tea_story"),
            favorite_types=data.get("profile_types") or None,
            taste_preferences=taste_str,
        )
        await state.clear()
        await callback.message.edit_text("✅ Чайный профиль сохранён!")
        await callback.message.answer(
            "🍵 Чайный дневник:", reply_markup=_tea_menu_kb().as_markup()
        )
        await callback.answer()
        return

    if tag == "custom":
        await state.set_state(TeaProfileFlow.custom_taste)
        await callback.message.answer("✏️ Напиши свой вкусовой тег:")
        await callback.answer()
        return

    selected = data.get("profile_tastes", set())
    if not isinstance(selected, set):
        selected = set()
    if tag in selected:
        selected.discard(tag)
    else:
        selected.add(tag)
    await state.update_data(profile_tastes=selected)
    await callback.message.edit_reply_markup(reply_markup=_tags_kb(selected).as_markup())
    await callback.answer()


@router.message(TeaProfileFlow.custom_taste)
async def tea_profile_custom_taste_text(message: Message, state: FSMContext) -> None:
    text = _trim_for_cb("ttag:", (message.text or "").strip().lower())
    if not text:
        await message.answer("Введи вкусовой тег:")
        return
    data = await state.get_data()
    selected = data.get("profile_tastes", set())
    if not isinstance(selected, set):
        selected = set()
    selected.add(text)
    await state.update_data(profile_tastes=selected)
    await state.set_state(TeaProfileFlow.tastes)
    await message.answer(
        f"✅ Тег «{esc(text)}» добавлен.\n\n"
        "👅 Выбирай ещё или нажми «Готово»:",
        reply_markup=_tags_kb(selected).as_markup(),
    )


# ==================== Запись чаепития ====================

@router.callback_query(F.data == "tea:write")
async def tea_write_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    profile = await get_tea_profile(session, user.id)
    if profile is None:
        await callback.message.answer(
            "☝️ Сначала заполни чайный профиль — это один раз."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="✍️ Заполнить профиль", callback_data="tea:profile_start")
        kb.adjust(1)
        await callback.message.answer("Начнём?", reply_markup=kb.as_markup())
        await callback.answer()
        return

    await state.set_state(TeaSessionFlow.name)
    await callback.message.answer("🍵 <b>Новое чаепитие</b>\n\nНазвание чая:")
    await callback.answer()


@router.message(TeaSessionFlow.name)
async def tea_session_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название чая:")
        return
    await state.update_data(tea_name=name)
    await state.set_state(TeaSessionFlow.tea_type)
    await message.answer(
        f"🍵 <b>{esc(name)}</b>\n\nВыбери вид чая:",
        reply_markup=_tea_type_kb().as_markup(),
    )


@router.callback_query(F.data == "tt:custom", TeaSessionFlow.tea_type)
async def tea_session_type_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaSessionFlow.custom_type)
    await callback.message.answer(
        "✏️ Напиши свой вид чая (например: габа, жасминовый, бай му дань):"
    )
    await callback.answer()


@router.message(TeaSessionFlow.custom_type)
async def tea_session_type_custom_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    text = _trim_for_cb("tt:custom:", (message.text or "").strip())
    if not text:
        await message.answer("Введи название вида чая:")
        return
    data = await state.get_data()
    code = f"custom:{text}"
    if data.get("edit_mode"):
        ts_id = data["edit_ts_id"]
        await state.clear()
        await update_tea_session(session, ts_id, tea_type=code)
        await message.answer(
            f"✅ Вид чая изменён на 🍵 {esc(text)}",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
        return
    await state.update_data(tea_type=code)
    await state.set_state(TeaSessionFlow.rating)
    await message.answer(
        f"🍵 <b>{esc(data['tea_name'])}</b> — 🍵 {esc(text)}\n\n"
        "⭐ Оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )


@router.callback_query(F.data.startswith("tt:"), TeaSessionFlow.tea_type)
async def tea_session_type(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    code = callback.data[3:]
    data = await state.get_data()
    if data.get("edit_mode"):
        ts_id = data["edit_ts_id"]
        await state.clear()
        await update_tea_session(session, ts_id, tea_type=code)
        await callback.message.edit_text(
            f"✅ Вид чая изменён на {_type_label(code)}",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
        await callback.answer()
        return
    await state.update_data(tea_type=code)
    await state.set_state(TeaSessionFlow.rating)
    await callback.message.edit_text(
        f"🍵 <b>{esc(data['tea_name'])}</b> — {_type_label(code)}\n\n"
        "⭐ Оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr:"), TeaSessionFlow.rating)
async def tea_session_rating(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    val = callback.data[3:]
    rating = None if val == "skip" else int(val)
    data = await state.get_data()
    if data.get("edit_mode"):
        ts_id = data["edit_ts_id"]
        await state.clear()
        await update_tea_session(session, ts_id, rating=rating)
        label = f"⭐ {rating}/10" if rating else "без оценки"
        await callback.message.edit_text(
            f"✅ Оценка изменена: {label}",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
        await callback.answer()
        return
    await state.update_data(tea_rating=rating)
    await state.set_state(TeaSessionFlow.tags)
    await state.update_data(tea_tags=set())

    rating_text = f"⭐ {rating}/10" if rating else "без оценки"
    await callback.message.edit_text(
        f"🍵 <b>{esc(data['tea_name'])}</b> — {_type_label(data['tea_type'])} — {rating_text}\n\n"
        "👅 Вкусовые теги (нажимай, потом «Готово»):",
        reply_markup=_tags_kb(set()).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ttag:"), TeaSessionFlow.tags)
async def tea_session_tags(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    tag = callback.data[5:]
    data = await state.get_data()

    if tag == "done" or tag == "skip":
        if data.get("edit_mode"):
            ts_id = data["edit_ts_id"]
            selected = data.get("tea_tags", set())
            tags_str = ", ".join(sorted(selected)) if isinstance(selected, set) and selected else None
            await state.clear()
            await update_tea_session(session, ts_id, taste_tags=tags_str)
            label = tags_str or "нет"
            await callback.message.edit_text(
                f"✅ Теги обновлены: {label}",
                reply_markup=_edit_menu_kb(ts_id).as_markup(),
            )
            await callback.answer()
            return
        await state.set_state(TeaSessionFlow.notes)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "📝 <b>Заметки</b>\n\n"
            "Аромат, вкус, послевкусие, параметры заваривания — "
            "всё в свободной форме.\n\n"
            "<i>Или «пропустить».</i>"
        )
        await callback.answer()
        return

    if tag == "custom":
        await state.set_state(TeaSessionFlow.custom_tag)
        await callback.message.answer("✏️ Напиши свой вкусовой тег:")
        await callback.answer()
        return

    selected = data.get("tea_tags", set())
    if not isinstance(selected, set):
        selected = set()
    if tag in selected:
        selected.discard(tag)
    else:
        selected.add(tag)
    await state.update_data(tea_tags=selected)
    await callback.message.edit_reply_markup(reply_markup=_tags_kb(selected).as_markup())
    await callback.answer()


@router.message(TeaSessionFlow.custom_tag)
async def tea_session_custom_tag_text(message: Message, state: FSMContext) -> None:
    text = _trim_for_cb("ttag:", (message.text or "").strip().lower())
    if not text:
        await message.answer("Введи вкусовой тег:")
        return
    data = await state.get_data()
    selected = data.get("tea_tags", set())
    if not isinstance(selected, set):
        selected = set()
    selected.add(text)
    await state.update_data(tea_tags=selected)
    await state.set_state(TeaSessionFlow.tags)
    await message.answer(
        f"✅ Тег «{esc(text)}» добавлен.\n\n"
        "👅 Выбирай ещё или нажми «Готово»:",
        reply_markup=_tags_kb(selected).as_markup(),
    )


@router.message(TeaSessionFlow.notes)
async def tea_session_notes(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    notes = None if text.lower() in ("пропустить", "skip", "-") else text
    await state.update_data(tea_notes=notes)
    await state.set_state(TeaSessionFlow.photo)
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить фото", callback_data="tp:no_photo")
    await message.answer(
        "📸 Отправь фото чая (до 3 штук), потом нажми «Готово».\n"
        "Или пропусти.",
        reply_markup=kb.as_markup(),
    )


@router.message(TeaSessionFlow.photo, F.photo)
async def tea_session_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos = data.get("tea_photos", [])
    if len(photos) >= 3:
        await message.answer("Максимум 3 фото. Нажми «Готово».")
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(tea_photos=photos)

    kb = InlineKeyboardBuilder()
    kb.button(text=f"✔️ Готово ({len(photos)} фото)", callback_data="tp:photos_done")
    await message.answer(
        f"📸 Фото {len(photos)}/3 принято.",
        reply_markup=kb.as_markup(),
    )


@router.message(TeaSessionFlow.photo, ~F.photo)
async def tea_session_photo_text(message: Message) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить фото", callback_data="tp:no_photo")
    await message.answer(
        "📸 Отправь фото или нажми «Пропустить фото».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.in_({"tp:no_photo", "tp:photos_done"}), TeaSessionFlow.photo)
async def tea_session_photo_done(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(TeaSessionFlow.qi)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✨ <b>Состояние (ча ци)</b>\n\nКак подействовал чай?",
        reply_markup=_cha_qi_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tq:"), TeaSessionFlow.qi)
async def tea_session_qi(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    val = callback.data[3:]
    cha_qi = None if val == "skip" else val

    data = await state.get_data()

    if data.get("edit_mode"):
        ts_id = data["edit_ts_id"]
        await state.clear()
        await update_tea_session(session, ts_id, cha_qi=cha_qi)
        label = CHA_QI_OPTIONS.get(cha_qi, "нет") if cha_qi else "нет"
        await callback.message.edit_text(
            f"✅ Ча ци обновлено: {label}",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
        await callback.answer()
        return

    tags_set = data.get("tea_tags", set())
    tags_str = ", ".join(sorted(tags_set)) if isinstance(tags_set, set) and tags_set else None
    photos = data.get("tea_photos", [])
    photo_str = ",".join(photos) if photos else None

    today = user_today(user)
    ts = await add_tea_session(
        session,
        user_id=user.id,
        tea_name=data["tea_name"],
        tea_type=data["tea_type"],
        rating=data.get("tea_rating"),
        taste_tags=tags_str,
        notes=data.get("tea_notes"),
        photo_file_ids=photo_str,
        cha_qi=cha_qi,
        private=user.tea_diary_private,
        session_date=today,
    )
    await state.clear()

    lines = ["✅ <b>Чаепитие записано!</b>\n"]
    lines.append(f"🍵 {esc(data['tea_name'])} — {_type_label(data['tea_type'])}")
    if data.get("tea_rating"):
        lines.append(f"⭐ {data['tea_rating']}/10")
    if tags_str:
        lines.append(f"👅 {tags_str}")
    if cha_qi and cha_qi != "none":
        qi_label = CHA_QI_OPTIONS.get(cha_qi, cha_qi)
        lines.append(f"✨ {qi_label}")
    if photos:
        lines.append(f"📸 {len(photos)} фото")

    coll_id = data.get("coll_item_id")
    if coll_id:
        item = await subtract_tea_grams(session, coll_id, 5)
        if item:
            lines.append(f"\n⚖️ Списано 5г из коллекции (осталось {item.remaining_grams}г)")
            if item.status == "finished":
                lines.append("✅ Этот чай закончился!")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=home_kb(),
    )
    await callback.answer()


# ==================== История ====================

def _session_card_text(s) -> str:
    lines = [f"<b>{s.session_date:%d.%m.%Y}</b> {_type_label(s.tea_type)} <b>{esc(s.tea_name)}</b>"]
    if s.rating:
        lines[0] += f" — ⭐ {s.rating}/10"
    if s.taste_tags:
        lines.append(f"👅 {esc(s.taste_tags)}")
    if s.notes:
        max_len = 800 if s.photo_file_ids else 3000
        preview = s.notes[:max_len] + ("…" if len(s.notes) > max_len else "")
        lines.append(f"📝 <i>{esc(preview)}</i>")
    if s.cha_qi and s.cha_qi != "none":
        qi = CHA_QI_OPTIONS.get(s.cha_qi, s.cha_qi)
        lines.append(f"✨ {qi}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("tea:history"))
async def tea_history(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    offset = page * PAGE_SIZE
    sessions = await list_tea_sessions(session, user.id, limit=PAGE_SIZE + 1, offset=offset)
    has_next = len(sessions) > PAGE_SIZE
    sessions = sessions[:PAGE_SIZE]

    if not sessions and page == 0:
        await callback.message.answer(
            "📚 Записей пока нет. Запиши первое чаепитие!",
            reply_markup=_tea_menu_kb().as_markup(),
        )
        await callback.answer()
        return

    await callback.message.answer("📚 <b>Мои чаепития:</b>")

    for i, s in enumerate(sessions):
        is_last = i == len(sessions) - 1
        card = _session_card_text(s)

        card_kb = InlineKeyboardBuilder()
        card_kb.button(text="✏️", callback_data=f"te:edit:{s.id}")
        card_kb.button(text="🗑", callback_data=f"te:del:{s.id}")
        if is_last:
            nav_row = []
            if page > 0:
                card_kb.button(text="⬅️", callback_data=f"tea:history:{page - 1}")
                nav_row.append(1)
            if has_next:
                card_kb.button(text="➡️", callback_data=f"tea:history:{page + 1}")
                nav_row.append(1)
            card_kb.button(text="⬅️ Чайный дневник", callback_data="go:tea")
            card_kb.adjust(2, *nav_row, 1)
        else:
            card_kb.adjust(2)

        if s.photo_file_ids:
            fids = s.photo_file_ids.split(",")
            try:
                await callback.message.answer_photo(
                    fids[0], caption=card, reply_markup=card_kb.as_markup(),
                )
                for fid in fids[1:]:
                    await callback.message.answer_photo(fid)
            except Exception:
                await callback.message.answer(card, reply_markup=card_kb.as_markup())
        else:
            await callback.message.answer(card, reply_markup=card_kb.as_markup())

    await callback.answer()


# ==================== Редактирование и удаление ====================


def _edit_menu_kb(ts_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍵 Название", callback_data=f"te:f:name:{ts_id}")
    kb.button(text="🏷 Вид чая", callback_data=f"te:f:type:{ts_id}")
    kb.button(text="⭐ Оценка", callback_data=f"te:f:rating:{ts_id}")
    kb.button(text="👅 Теги", callback_data=f"te:f:tags:{ts_id}")
    kb.button(text="📝 Заметки", callback_data=f"te:f:notes:{ts_id}")
    kb.button(text="📸 Добавить фото", callback_data=f"te:f:photo:{ts_id}")
    kb.button(text="✨ Ча ци", callback_data=f"te:f:qi:{ts_id}")
    kb.button(text="⬅️ Назад", callback_data="tea:history")
    kb.adjust(2, 2, 2, 1, 1)
    return kb


@router.callback_query(F.data.startswith("te:edit:"))
async def tea_edit_menu(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    ts_id = int(callback.data.split(":")[2])
    ts = await get_tea_session(session, ts_id)
    if not ts or ts.user_id != user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    card = _session_card_text(ts)
    await callback.message.answer(
        f"✏️ <b>Редактирование</b>\n\n{card}\n\nЧто изменить?",
        reply_markup=_edit_menu_kb(ts_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:f:name:"))
async def tea_edit_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaEditFlow.name)
    await state.update_data(edit_ts_id=ts_id)
    await callback.message.answer("🍵 Введи новое название чая:")
    await callback.answer()


@router.message(TeaEditFlow.name)
async def tea_edit_name_save(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введи название чая:")
        return
    data = await state.get_data()
    ts_id = data["edit_ts_id"]
    await state.clear()
    ts = await update_tea_session(session, ts_id, tea_name=text)
    if ts and ts.user_id == user.id:
        await message.answer(
            f"✅ Название изменено на «{esc(text)}»",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
    else:
        await message.answer("Запись не найдена.")


@router.callback_query(F.data.startswith("te:f:type:"))
async def tea_edit_type_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaSessionFlow.tea_type)
    await state.update_data(edit_ts_id=ts_id, edit_mode=True)
    await callback.message.answer(
        "🏷 Выбери новый вид чая:",
        reply_markup=_tea_type_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:f:rating:"))
async def tea_edit_rating_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaSessionFlow.rating)
    await state.update_data(edit_ts_id=ts_id, edit_mode=True)
    await callback.message.answer(
        "⭐ Новая оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:f:tags:"))
async def tea_edit_tags_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaSessionFlow.tags)
    await state.update_data(edit_ts_id=ts_id, edit_mode=True, tea_tags=set())
    await callback.message.answer(
        "👅 Выбери новые вкусовые теги:",
        reply_markup=_tags_kb(set()).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:f:notes:"))
async def tea_edit_notes_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaEditFlow.notes)
    await state.update_data(edit_ts_id=ts_id)
    await callback.message.answer(
        "📝 Введи новые заметки (или «пропустить» чтобы очистить):"
    )
    await callback.answer()


@router.message(TeaEditFlow.notes)
async def tea_edit_notes_save(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    text = (message.text or "").strip()
    notes = None if text.lower() in ("пропустить", "skip", "-") else text
    data = await state.get_data()
    ts_id = data["edit_ts_id"]
    await state.clear()
    ts = await update_tea_session(session, ts_id, notes=notes)
    if ts and ts.user_id == user.id:
        label = "обновлены" if notes else "очищены"
        await message.answer(
            f"✅ Заметки {label}.",
            reply_markup=_edit_menu_kb(ts_id).as_markup(),
        )
    else:
        await message.answer("Запись не найдена.")


@router.callback_query(F.data.startswith("te:f:photo:"))
async def tea_edit_photo_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaEditFlow.photo)
    await state.update_data(edit_ts_id=ts_id, edit_photos=[])
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data=f"te:edit:{ts_id}")
    await callback.message.answer(
        "📸 Отправь фото (до 3 штук), потом нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(TeaEditFlow.photo, F.photo)
async def tea_edit_photo_recv(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos = data.get("edit_photos", [])
    if len(photos) >= 3:
        await message.answer("Максимум 3 фото. Нажми «Готово».")
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(edit_photos=photos)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✔️ Готово ({len(photos)} фото)", callback_data="te:photo_done")
    await message.answer(f"📸 Фото {len(photos)}/3 принято.", reply_markup=kb.as_markup())


@router.callback_query(F.data == "te:photo_done", TeaEditFlow.photo)
async def tea_edit_photo_save(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    ts_id = data["edit_ts_id"]
    new_photos = data.get("edit_photos", [])
    await state.clear()

    ts = await get_tea_session(session, ts_id)
    if not ts or ts.user_id != user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    existing = ts.photo_file_ids.split(",") if ts.photo_file_ids else []
    combined = (existing + new_photos)[:3]
    photo_str = ",".join(combined) if combined else None
    await update_tea_session(session, ts_id, photo_file_ids=photo_str)

    await callback.message.edit_text(
        f"✅ Фото обновлены ({len(combined)} шт.)",
        reply_markup=_edit_menu_kb(ts_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:f:qi:"))
async def tea_edit_qi_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[3])
    await state.set_state(TeaSessionFlow.qi)
    await state.update_data(edit_ts_id=ts_id, edit_mode=True)
    await callback.message.answer(
        "✨ Как подействовал чай?",
        reply_markup=_cha_qi_kb().as_markup(),
    )
    await callback.answer()


# -- Удаление --

@router.callback_query(F.data.startswith("te:del:"))
async def tea_delete_confirm(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    ts_id = int(callback.data.split(":")[2])
    ts = await get_tea_session(session, ts_id)
    if not ts or ts.user_id != user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=f"te:delok:{ts_id}")
    kb.button(text="❌ Отмена", callback_data="tea:history")
    kb.adjust(2)
    await callback.message.answer(
        f"🗑 Удалить запись <b>{esc(ts.tea_name)}</b> "
        f"({ts.session_date:%d.%m.%Y})?",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("te:delok:"))
async def tea_delete_execute(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    ts_id = int(callback.data.split(":")[2])
    ts = await get_tea_session(session, ts_id)
    if not ts or ts.user_id != user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    name = ts.tea_name
    await delete_tea_session(session, ts_id)
    await callback.message.edit_text(f"✅ Запись «{esc(name)}» удалена.")
    await callback.message.answer(
        "🍵 Чайный дневник:", reply_markup=_tea_menu_kb(user).as_markup()
    )
    await callback.answer()


# ==================== Статистика ====================

@router.callback_query(F.data == "tea:stats")
async def tea_stats(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    total = await count_tea_sessions(session, user.id)
    if total == 0:
        await callback.message.answer(
            "📊 Статистика появится после первого чаепития.",
            reply_markup=_tea_menu_kb().as_markup(),
        )
        await callback.answer()
        return

    lines = ["📊 <b>Чайная статистика</b>\n"]
    lines.append(f"🍵 Всего чаепитий: <b>{total}</b>")

    avg = await avg_tea_rating(session, user.id)
    if avg:
        lines.append(f"⭐ Средняя оценка: <b>{avg}</b>/10")

    dates = await tea_session_dates(session, user.id)
    streak, best = _calc_tea_streak(dates, user_today(user))
    lines.append(f"🔥 Чайная серия: <b>{streak}</b> дн.")
    lines.append(f"🏆 Рекорд серии: <b>{best}</b> дн.")

    type_data = await tea_type_stats(session, user.id)
    if type_data:
        lines.append("\n<b>По видам:</b>")
        for tea_type, cnt in type_data:
            pct = round(cnt / total * 100)
            lines.append(f"  {_type_label(tea_type)}: {cnt} ({pct}%)")

    name_data = await tea_name_stats(session, user.id)
    if name_data:
        lines.append("\n<b>Топ чаёв:</b>")
        for i, (name, cnt) in enumerate(name_data, 1):
            lines.append(f"  {i}. {esc(name)} — {cnt} раз")

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="go:tea")
    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await callback.answer()


# ==================== Приватность ====================

@router.callback_query(F.data == "tea:toggle_privacy")
async def tea_toggle_privacy(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    new_val = not user.tea_diary_private
    await update_user_settings(session, user, tea_diary_private=new_val)
    label = "🔒 скрыты" if new_val else "🔓 открыты"
    await callback.answer(f"Чайные записи теперь {label}", show_alert=True)
    await callback.message.edit_reply_markup(
        reply_markup=_tea_menu_kb(user).as_markup()
    )


# ==================== Чайная лента ====================

def _feed_card_text(s, author_name: str) -> str:
    lines = [
        f"<b>{s.session_date:%d.%m.%Y}</b> — 👤 <b>{esc(author_name)}</b>",
        f"{_type_label(s.tea_type)} <b>{esc(s.tea_name)}</b>",
    ]
    if s.rating:
        lines[-1] += f" — ⭐ {s.rating}/10"
    if s.taste_tags:
        lines.append(f"👅 {esc(s.taste_tags)}")
    if s.notes:
        max_len = 700 if s.photo_file_ids else 3000
        preview = s.notes[:max_len] + ("…" if len(s.notes) > max_len else "")
        lines.append(f"📝 <i>{esc(preview)}</i>")
    if s.cha_qi and s.cha_qi != "none":
        qi = CHA_QI_OPTIONS.get(s.cha_qi, s.cha_qi)
        lines.append(f"✨ {qi}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("tea:feed:"))
async def tea_feed(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    page = int(callback.data.split(":")[2])
    offset = page * PAGE_SIZE
    sessions = await list_public_tea_sessions(session, limit=PAGE_SIZE + 1, offset=offset)
    has_next = len(sessions) > PAGE_SIZE
    sessions = sessions[:PAGE_SIZE]

    if not sessions and page == 0:
        await callback.message.answer(
            "🌍 Пока никто не делился чаепитиями.\n"
            "Будь первым — запиши чаепитие и открой записи!",
            reply_markup=_tea_menu_kb(user).as_markup(),
        )
        await callback.answer()
        return

    await callback.message.answer("🌍 <b>Чайная лента</b>")

    nav_kb = InlineKeyboardBuilder()
    if page > 0:
        nav_kb.button(text="⬅️", callback_data=f"tea:feed:{page - 1}")
    if has_next:
        nav_kb.button(text="➡️", callback_data=f"tea:feed:{page + 1}")
    nav_kb.button(text="⬅️ Чайный дневник", callback_data="go:tea")
    nav_row = []
    if page > 0:
        nav_row.append("⬅️")
    if has_next:
        nav_row.append("➡️")
    if nav_row:
        nav_kb.adjust(len(nav_row), 1)
    else:
        nav_kb.adjust(1)

    for i, s in enumerate(sessions):
        is_last = i == len(sessions) - 1
        author = display_name(s.user) if s.user else "?"
        card = _feed_card_text(s, author)

        card_kb = InlineKeyboardBuilder()
        if s.user_id != user.id:
            card_kb.button(text=f"💬 Написать", callback_data=f"tea:msg:{s.id}")
        markup = card_kb.as_markup() if card_kb.export() else None

        if is_last:
            markup = nav_kb.as_markup()

        if s.photo_file_ids:
            fids = s.photo_file_ids.split(",")
            try:
                await callback.message.answer_photo(
                    fids[0], caption=card, reply_markup=markup,
                )
                for fid in fids[1:]:
                    await callback.message.answer_photo(fid)
            except Exception:
                await callback.message.answer(card, reply_markup=markup)
        else:
            await callback.message.answer(card, reply_markup=markup)

    await callback.answer()


# ==================== Чайные сообщения ====================

@router.callback_query(F.data.startswith("tea:msg:"))
async def tea_msg_start(callback: CallbackQuery, state: FSMContext) -> None:
    ts_id = int(callback.data.split(":")[2])
    await state.set_state(TeaMessageFlow.text)
    await state.update_data(tea_msg_session_id=ts_id)
    await callback.message.answer(
        "💬 <b>Написать автору</b>\n\n"
        "Спроси где купил, как заваривает, поделись мнением.\n"
        "Напиши сообщение (до 500 символов):"
    )
    await callback.answer()


@router.message(TeaMessageFlow.text)
async def tea_msg_send(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    data = await state.get_data()
    ts_id = data.get("tea_msg_session_id")
    await state.clear()

    text = (message.text or "").strip()[:500]
    if not text:
        await message.answer("Пустое сообщение не отправлю.")
        return

    ts = await get_tea_session(session, ts_id) if ts_id else None
    if not ts:
        await message.answer("Запись не найдена.")
        return

    sender = display_name(user)
    tea_info = f"{_type_label(ts.tea_type)} {ts.tea_name}"
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"msg:{user.telegram_id}")
    try:
        await message.bot.send_message(
            ts.user.telegram_id,
            f"🍵💬 <b>Сообщение от {esc(sender)}</b>\n"
            f"По записи: {esc(tea_info)}\n\n"
            f"{esc(text)}",
            reply_markup=kb.as_markup(),
        )
        await message.answer("✅ Сообщение отправлено!")
    except Exception:
        await message.answer("Не удалось отправить сообщение.")


# ==================== Чайный профиль другого пользователя ====================

@router.callback_query(F.data.startswith("tea:user:"))
async def tea_user_profile(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    target_tg = int(callback.data.split(":")[2])
    target = await get_user_by_tg(session, target_tg)
    if not target:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    name = display_name(target)
    profile = await get_tea_profile(session, target.id)
    sessions = await list_user_public_tea_sessions(session, target.id, limit=5)

    lines = [f"🍵 <b>Чайный профиль: {esc(name)}</b>\n"]
    if profile:
        if profile.tea_story:
            story = profile.tea_story[:200] + ("…" if len(profile.tea_story) > 200 else "")
            lines.append(f"📖 <i>{esc(story)}</i>\n")
        if profile.favorite_types:
            types = [_type_label(t) for t in profile.favorite_types.split(",")]
            lines.append(f"❤️ Любимые: {', '.join(types)}")
        if profile.taste_preferences:
            lines.append(f"👅 Вкусы: {profile.taste_preferences}")

    if sessions:
        lines.append(f"\n<b>Последние чаепития:</b>")
        for s in sessions:
            entry = f"{_type_label(s.tea_type)} <b>{esc(s.tea_name)}</b>"
            if s.rating:
                entry += f" — ⭐ {s.rating}/10"
            lines.append(entry)
    else:
        lines.append("\nНет публичных записей.")

    kb = InlineKeyboardBuilder()
    for s in sessions:
        kb.button(
            text=f"💬 {s.tea_name[:20]}",
            callback_data=f"tea:msg:{s.id}",
        )
    kb.adjust(1)
    kb.button(text="⬅️ Лента", callback_data="tea:feed:0")
    await callback.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await callback.answer()


# ==================== Коллекция чая ====================


def _coll_card_text(item) -> str:
    lines = [f"{_type_label(item.tea_type)} <b>{esc(item.tea_name)}</b>"]
    if item.year:
        lines[0] += f" ({item.year})"
    if item.remaining_grams is not None and item.weight_grams is not None:
        lines.append(f"⚖️ {item.remaining_grams}г / {item.weight_grams}г")
    elif item.weight_grams is not None:
        lines.append(f"⚖️ {item.weight_grams}г")
    if item.vendor:
        lines.append(f"🏪 {esc(item.vendor)}")
    if item.price:
        lines.append(f"💰 {esc(item.price)}")
    if item.notes:
        preview = item.notes[:200] + ("…" if len(item.notes) > 200 else "")
        lines.append(f"📝 <i>{esc(preview)}</i>")
    if item.status == "finished":
        lines.append("✅ Закончился")
    return "\n".join(lines)


@router.callback_query(F.data == "tc:list")
async def tea_collection_list(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    items = await list_tea_collection(session, user.id)
    if not items:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить чай", callback_data="tc:add")
        kb.button(text="⬅️ Назад", callback_data="go:tea")
        kb.adjust(1)
        await callback.message.answer(
            "🗄 <b>Моя коллекция</b>\n\nПока пусто. Добавь свой первый чай!",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    await callback.message.answer(f"🗄 <b>Моя коллекция</b> ({len(items)} чаёв):")
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        card = _coll_card_text(item)
        kb = InlineKeyboardBuilder()
        kb.button(text="🍵 Заварить", callback_data=f"tc:brew:{item.id}")
        kb.button(text="✏️", callback_data=f"tc:edit:{item.id}")
        kb.button(text="🗑", callback_data=f"tc:del:{item.id}")
        if is_last:
            kb.button(text="➕ Добавить", callback_data="tc:add")
            kb.button(text="⬅️ Назад", callback_data="go:tea")
            kb.adjust(3, 1, 1)
        else:
            kb.adjust(3)
        await callback.message.answer(card, reply_markup=kb.as_markup())
    await callback.answer()


# -- Добавление в коллекцию --

@router.callback_query(F.data == "tc:add")
async def tea_coll_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaCollectionFlow.name)
    await callback.message.answer("🍵 <b>Добавить чай в коллекцию</b>\n\nНазвание чая:")
    await callback.answer()


@router.message(TeaCollectionFlow.name)
async def tea_coll_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название чая:")
        return
    await state.update_data(coll_name=name)
    await state.set_state(TeaCollectionFlow.tea_type)
    await message.answer(
        f"🍵 <b>{esc(name)}</b>\n\nВыбери вид чая:",
        reply_markup=_tea_type_kb().as_markup(),
    )


@router.callback_query(F.data == "tt:custom", TeaCollectionFlow.tea_type)
async def tea_coll_type_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TeaCollectionFlow.custom_type)
    await callback.message.answer("✏️ Напиши свой вид чая:")
    await callback.answer()


@router.message(TeaCollectionFlow.custom_type)
async def tea_coll_type_custom_text(message: Message, state: FSMContext) -> None:
    text = _trim_for_cb("tt:custom:", (message.text or "").strip())
    if not text:
        await message.answer("Введи название вида чая:")
        return
    await state.update_data(coll_type=f"custom:{text}")
    await state.set_state(TeaCollectionFlow.weight)
    await message.answer("⚖️ Вес в граммах (или «пропустить»):")


@router.callback_query(F.data.startswith("tt:"), TeaCollectionFlow.tea_type)
async def tea_coll_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data[3:]
    await state.update_data(coll_type=code)
    await state.set_state(TeaCollectionFlow.weight)
    await callback.message.edit_text(
        f"✅ Вид: {_type_label(code)}\n\n⚖️ Вес в граммах (или «пропустить»):"
    )
    await callback.answer()


@router.message(TeaCollectionFlow.weight)
async def tea_coll_weight(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    weight = None
    if text.lower() not in ("пропустить", "skip", "-"):
        try:
            weight = int(text.replace("г", "").replace("g", "").strip())
        except ValueError:
            await message.answer("Введи число граммов или «пропустить»:")
            return
    await state.update_data(coll_weight=weight)
    await state.set_state(TeaCollectionFlow.price)
    await message.answer("💰 Цена (в свободной форме, напр. «500₽» или «$15/50г»). Или «пропустить»:")


@router.message(TeaCollectionFlow.price)
async def tea_coll_price(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    price = None if text.lower() in ("пропустить", "skip", "-") else text
    await state.update_data(coll_price=price)
    await state.set_state(TeaCollectionFlow.vendor)
    await message.answer("🏪 Где купил (магазин, ссылка)? Или «пропустить»:")


@router.message(TeaCollectionFlow.vendor)
async def tea_coll_vendor(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    vendor = None if text.lower() in ("пропустить", "skip", "-") else text
    await state.update_data(coll_vendor=vendor)
    await state.set_state(TeaCollectionFlow.year)
    await message.answer("📅 Год сбора/прессовки (напр. 2019)? Или «пропустить»:")


@router.message(TeaCollectionFlow.year)
async def tea_coll_year(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    year = None
    if text.lower() not in ("пропустить", "skip", "-"):
        try:
            year = int(text)
        except ValueError:
            await message.answer("Введи год числом или «пропустить»:")
            return
    await state.update_data(coll_year=year)
    await state.set_state(TeaCollectionFlow.notes)
    await message.answer("📝 Заметки (происхождение, форма, впечатления)? Или «пропустить»:")


@router.message(TeaCollectionFlow.notes)
async def tea_coll_notes_save(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    text = (message.text or "").strip()
    notes = None if text.lower() in ("пропустить", "skip", "-") else text
    data = await state.get_data()
    await state.clear()

    weight = data.get("coll_weight")
    item = await add_tea_collection(
        session,
        user_id=user.id,
        tea_name=data["coll_name"],
        tea_type=data["coll_type"],
        weight_grams=weight,
        remaining_grams=weight,
        price=data.get("coll_price"),
        vendor=data.get("coll_vendor"),
        year=data.get("coll_year"),
        notes=notes,
    )

    card = _coll_card_text(item)
    kb = InlineKeyboardBuilder()
    kb.button(text="🗄 Коллекция", callback_data="tc:list")
    kb.button(text="🏠 Меню", callback_data="go:menu")
    kb.adjust(2)
    await message.answer(f"✅ <b>Добавлено в коллекцию!</b>\n\n{card}", reply_markup=kb.as_markup())


# -- Рандомайзер --

@router.callback_query(F.data == "tc:random")
async def tea_random(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item = await get_random_tea(session, user.id)
    if not item:
        await callback.answer("Коллекция пуста — добавь чаи!", show_alert=True)
        return
    card = _coll_card_text(item)
    kb = InlineKeyboardBuilder()
    kb.button(text="🍵 Заварить этот!", callback_data=f"tc:brew:{item.id}")
    kb.button(text="🎲 Ещё раз", callback_data="tc:random")
    kb.button(text="⬅️ Назад", callback_data="go:tea")
    kb.adjust(2, 1)
    await callback.message.answer(
        f"🎲 <b>Сегодня завари:</b>\n\n{card}",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# -- Заварить из коллекции (создать запись + списать граммы) --

@router.callback_query(F.data.startswith("tc:brew:"))
async def tea_coll_brew(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    item_id = int(callback.data.split(":")[2])
    item = await get_tea_collection_item(session, item_id)
    if not item:
        await callback.answer("Чай не найден", show_alert=True)
        return

    await state.set_state(TeaSessionFlow.rating)
    await state.update_data(
        tea_name=item.tea_name,
        tea_type=item.tea_type,
        coll_item_id=item.id,
    )
    await callback.message.answer(
        f"🍵 Завариваем <b>{esc(item.tea_name)}</b> — {_type_label(item.tea_type)}\n\n"
        "⭐ Оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )
    await callback.answer()


# -- Редактирование коллекции --

def _coll_edit_kb(item_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍵 Название", callback_data=f"tc:ef:name:{item_id}")
    kb.button(text="⚖️ Вес", callback_data=f"tc:ef:weight:{item_id}")
    kb.button(text="💰 Цена", callback_data=f"tc:ef:price:{item_id}")
    kb.button(text="🏪 Продавец", callback_data=f"tc:ef:vendor:{item_id}")
    kb.button(text="📝 Заметки", callback_data=f"tc:ef:notes:{item_id}")
    kb.button(text="➖ Списать граммы", callback_data=f"tc:ef:sub:{item_id}")
    kb.button(text="⬅️ Коллекция", callback_data="tc:list")
    kb.adjust(2, 2, 1, 1, 1)
    return kb


@router.callback_query(F.data.startswith("tc:edit:"))
async def tea_coll_edit_menu(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item_id = int(callback.data.split(":")[2])
    item = await get_tea_collection_item(session, item_id)
    if not item or item.user_id != user.id:
        await callback.answer("Не найдено", show_alert=True)
        return
    card = _coll_card_text(item)
    await callback.message.answer(
        f"✏️ <b>Редактирование</b>\n\n{card}\n\nЧто изменить?",
        reply_markup=_coll_edit_kb(item_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tc:ef:name:"))
async def tea_coll_edit_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.name)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("🍵 Новое название:")
    await callback.answer()


@router.message(TeaCollEditFlow.name)
async def tea_coll_edit_name_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введи название:")
        return
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    await update_tea_collection_item(session, item_id, tea_name=text)
    await message.answer(f"✅ Название изменено на «{esc(text)}»", reply_markup=_coll_edit_kb(item_id).as_markup())


@router.callback_query(F.data.startswith("tc:ef:weight:"))
async def tea_coll_edit_weight_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.weight)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("⚖️ Новый вес (г) — обновит и общий, и остаток:")
    await callback.answer()


@router.message(TeaCollEditFlow.weight)
async def tea_coll_edit_weight_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    try:
        weight = int(text.replace("г", "").replace("g", "").strip())
    except ValueError:
        await message.answer("Введи число граммов:")
        return
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    await update_tea_collection_item(session, item_id, weight_grams=weight, remaining_grams=weight)
    await message.answer(f"✅ Вес обновлён: {weight}г", reply_markup=_coll_edit_kb(item_id).as_markup())


@router.callback_query(F.data.startswith("tc:ef:price:"))
async def tea_coll_edit_price_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.price)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("💰 Новая цена:")
    await callback.answer()


@router.message(TeaCollEditFlow.price)
async def tea_coll_edit_price_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    await update_tea_collection_item(session, item_id, price=text)
    await message.answer(f"✅ Цена обновлена", reply_markup=_coll_edit_kb(item_id).as_markup())


@router.callback_query(F.data.startswith("tc:ef:vendor:"))
async def tea_coll_edit_vendor_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.vendor)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("🏪 Новый продавец/магазин:")
    await callback.answer()


@router.message(TeaCollEditFlow.vendor)
async def tea_coll_edit_vendor_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    await update_tea_collection_item(session, item_id, vendor=text)
    await message.answer(f"✅ Продавец обновлён", reply_markup=_coll_edit_kb(item_id).as_markup())


@router.callback_query(F.data.startswith("tc:ef:notes:"))
async def tea_coll_edit_notes_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.notes)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("📝 Новые заметки (или «пропустить» чтобы очистить):")
    await callback.answer()


@router.message(TeaCollEditFlow.notes)
async def tea_coll_edit_notes_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    notes = None if text.lower() in ("пропустить", "skip", "-") else text
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    await update_tea_collection_item(session, item_id, notes=notes)
    await message.answer(f"✅ Заметки обновлены", reply_markup=_coll_edit_kb(item_id).as_markup())


@router.callback_query(F.data.startswith("tc:ef:sub:"))
async def tea_coll_subtract_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[3])
    await state.set_state(TeaCollEditFlow.subtract)
    await state.update_data(coll_edit_id=item_id)
    await callback.message.answer("➖ Сколько граммов списать?")
    await callback.answer()


@router.message(TeaCollEditFlow.subtract)
async def tea_coll_subtract_save(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    text = (message.text or "").strip()
    try:
        grams = int(text.replace("г", "").replace("g", "").strip())
    except ValueError:
        await message.answer("Введи число граммов:")
        return
    data = await state.get_data()
    item_id = data["coll_edit_id"]
    await state.clear()
    item = await subtract_tea_grams(session, item_id, grams)
    if item:
        status = ""
        if item.status == "finished":
            status = "\n✅ Чай закончился!"
        await message.answer(
            f"➖ Списано {grams}г. Остаток: {item.remaining_grams}г{status}",
            reply_markup=_coll_edit_kb(item_id).as_markup(),
        )
    else:
        await message.answer("Чай не найден.")


# -- Удаление из коллекции --

@router.callback_query(F.data.startswith("tc:del:"))
async def tea_coll_delete_confirm(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item_id = int(callback.data.split(":")[2])
    item = await get_tea_collection_item(session, item_id)
    if not item or item.user_id != user.id:
        await callback.answer("Не найдено", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=f"tc:delok:{item_id}")
    kb.button(text="❌ Отмена", callback_data="tc:list")
    kb.adjust(2)
    await callback.message.answer(
        f"🗑 Удалить <b>{esc(item.tea_name)}</b> из коллекции?",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tc:delok:"))
async def tea_coll_delete_execute(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    item_id = int(callback.data.split(":")[2])
    item = await get_tea_collection_item(session, item_id)
    if not item or item.user_id != user.id:
        await callback.answer("Не найдено", show_alert=True)
        return
    name = item.tea_name
    await delete_tea_collection_item(session, item_id)
    await callback.message.edit_text(f"✅ «{esc(name)}» удалён из коллекции.")
    await callback.message.answer("🗄 Коллекция:", reply_markup=_tea_menu_kb(user).as_markup())
    await callback.answer()


# ==================== Вспомогательные ====================


def _calc_tea_streak(dates: list[date], today: date) -> tuple[int, int]:
    if not dates:
        return 0, 0
    date_set = set(dates)
    streak = 0
    d = today
    while d in date_set:
        streak += 1
        d -= timedelta(days=1)
    if streak == 0 and (today - timedelta(days=1)) in date_set:
        d = today - timedelta(days=1)
        while d in date_set:
            streak += 1
            d -= timedelta(days=1)

    best = 0
    current = 0
    for d in sorted(date_set):
        if current == 0 or d == prev + timedelta(days=1):
            current += 1
        else:
            current = 1
        if current > best:
            best = current
        prev = d
    return streak, best
