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
    add_tea_session,
    avg_tea_rating,
    count_tea_sessions,
    get_tea_profile,
    get_tea_session,
    get_user_by_tg,
    list_public_tea_sessions,
    list_tea_sessions,
    list_user_public_tea_sessions,
    list_users,
    tea_name_stats,
    tea_session_dates,
    tea_type_stats,
    update_user_settings,
    upsert_tea_profile,
)
from keyboards.nav import home_kb
from states import TeaMessageFlow, TeaProfileFlow, TeaSessionFlow
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
async def tea_session_type_custom_text(message: Message, state: FSMContext) -> None:
    text = _trim_for_cb("tt:custom:", (message.text or "").strip())
    if not text:
        await message.answer("Введи название вида чая:")
        return
    await state.update_data(tea_type=f"custom:{text}")
    await state.set_state(TeaSessionFlow.rating)
    data = await state.get_data()
    await message.answer(
        f"🍵 <b>{esc(data['tea_name'])}</b> — 🍵 {esc(text)}\n\n"
        "⭐ Оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )


@router.callback_query(F.data.startswith("tt:"), TeaSessionFlow.tea_type)
async def tea_session_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data[3:]
    await state.update_data(tea_type=code)
    await state.set_state(TeaSessionFlow.rating)
    data = await state.get_data()
    await callback.message.edit_text(
        f"🍵 <b>{esc(data['tea_name'])}</b> — {_type_label(code)}\n\n"
        "⭐ Оценка (1–10):",
        reply_markup=_rating_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr:"), TeaSessionFlow.rating)
async def tea_session_rating(callback: CallbackQuery, state: FSMContext) -> None:
    val = callback.data[3:]
    rating = None if val == "skip" else int(val)
    await state.update_data(tea_rating=rating)
    await state.set_state(TeaSessionFlow.tags)
    await state.update_data(tea_tags=set())

    rating_text = f"⭐ {rating}/10" if rating else "без оценки"
    data = await state.get_data()
    await callback.message.edit_text(
        f"🍵 <b>{esc(data['tea_name'])}</b> — {_type_label(data['tea_type'])} — {rating_text}\n\n"
        "👅 Вкусовые теги (нажимай, потом «Готово»):",
        reply_markup=_tags_kb(set()).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ttag:"), TeaSessionFlow.tags)
async def tea_session_tags(callback: CallbackQuery, state: FSMContext) -> None:
    tag = callback.data[5:]
    data = await state.get_data()

    if tag == "done" or tag == "skip":
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


@router.callback_query(F.data == "tea:history")
async def tea_history(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    sessions = await list_tea_sessions(session, user.id, limit=10)
    if not sessions:
        await callback.message.answer(
            "📚 Записей пока нет. Запиши первое чаепитие!",
            reply_markup=_tea_menu_kb().as_markup(),
        )
        await callback.answer()
        return

    await callback.message.answer("📚 <b>Последние чаепития:</b>")

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="go:tea")
    last_kb = kb.as_markup()

    for i, s in enumerate(sessions):
        is_last = i == len(sessions) - 1
        markup = last_kb if is_last else None
        card = _session_card_text(s)

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
