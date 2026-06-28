"""Чайный дневник: профиль, запись чаепитий, история, статистика."""
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
    list_tea_sessions,
    tea_name_stats,
    tea_session_dates,
    tea_type_stats,
    upsert_tea_profile,
)
from keyboards.nav import home_kb
from states import TeaProfileFlow, TeaSessionFlow
from utils import esc, user_today

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
    "сливочный", "минеральный", "пряный", "кислинка",
    "сладость", "горчинка", "терпкость", "свежесть",
]

CHA_QI_OPTIONS = {
    "vigor": "⚡ бодрит",
    "relax": "😌 расслабляет",
    "warm": "🔥 согревает",
    "satiety": "🍽 сытость",
    "meditate": "🧘 медитативный",
    "none": "🤷 не заметил",
}


def _tea_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍵 Записать чаепитие", callback_data="tea:write")
    kb.button(text="📚 Мои записи", callback_data="tea:history")
    kb.button(text="📊 Чайная статистика", callback_data="tea:stats")
    kb.button(text="👤 Мой чайный профиль", callback_data="tea:profile")
    kb.adjust(1)
    return kb


def _tea_type_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code, label in TEA_TYPES.items():
        emoji = TEA_TYPE_EMOJI[code]
        kb.button(text=f"{emoji} {label}", callback_data=f"tt:{code}")
    kb.adjust(3, 3, 3)
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
        kb.button(text=f"{mark}{tag}", callback_data=f"tg:{tag}")
    kb.button(text="✔️ Готово", callback_data="tg:done")
    kb.button(text="Пропустить", callback_data="tg:skip")
    kb.adjust(2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1)
    return kb


def _cha_qi_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code, label in CHA_QI_OPTIONS.items():
        kb.button(text=label, callback_data=f"tq:{code}")
    kb.button(text="Пропустить", callback_data="tq:skip")
    kb.adjust(2, 2, 2, 1)
    return kb


def _type_label(code: str) -> str:
    emoji = TEA_TYPE_EMOJI.get(code, "🍵")
    name = TEA_TYPES.get(code, code)
    return f"{emoji} {name}"


# ==================== Главное меню ====================

@router.message(Command("tea"))
@router.message(F.text == "🍵 Чай")
async def cmd_tea(message: Message) -> None:
    await show_tea_menu(message)


async def show_tea_menu(message: Message) -> None:
    await message.answer(
        "🍵 <b>Чайный дневник</b>\n"
        "Записывай чаепития, отслеживай вкусы и серии.",
        reply_markup=_tea_menu_kb().as_markup(),
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


@router.message(TeaProfileFlow.story)
async def tea_profile_story(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    story = None if text.lower() in ("пропустить", "skip", "-") else text
    await state.update_data(tea_story=story)
    await state.set_state(TeaProfileFlow.types)
    kb = _tea_type_kb()
    kb.button(text="✔️ Готово", callback_data="tp:types_done")
    kb.adjust(3, 3, 3, 1)
    await message.answer(
        "❤️ <b>Любимые виды чая</b>\n\n"
        "Выбери один или несколько (нажимай, потом «Готово»):",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("tp:tt:"), TeaProfileFlow.types)
async def tea_profile_toggle_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data[6:]
    data = await state.get_data()
    selected = set(data.get("profile_types", "").split(",")) - {""}
    if code in selected:
        selected.discard(code)
    else:
        selected.add(code)
    await state.update_data(profile_types=",".join(selected))

    kb = InlineKeyboardBuilder()
    for c, label in TEA_TYPES.items():
        emoji = TEA_TYPE_EMOJI[c]
        mark = "✅ " if c in selected else ""
        kb.button(text=f"{mark}{emoji} {label}", callback_data=f"tp:tt:{c}")
    kb.button(text="✔️ Готово", callback_data="tp:types_done")
    kb.adjust(3, 3, 3, 1)
    await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("tt:"), TeaProfileFlow.types)
async def tea_profile_toggle_type_alt(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data[3:]
    data = await state.get_data()
    selected = set(data.get("profile_types", "").split(",")) - {""}
    if code in selected:
        selected.discard(code)
    else:
        selected.add(code)
    await state.update_data(profile_types=",".join(selected))

    kb = InlineKeyboardBuilder()
    for c, label in TEA_TYPES.items():
        emoji = TEA_TYPE_EMOJI[c]
        mark = "✅ " if c in selected else ""
        kb.button(text=f"{mark}{emoji} {label}", callback_data=f"tt:{c}")
    kb.button(text="✔️ Готово", callback_data="tp:types_done")
    kb.adjust(3, 3, 3, 1)
    await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
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


@router.callback_query(F.data.startswith("tg:"), TeaProfileFlow.tastes)
async def tea_profile_toggle_taste(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    tag = callback.data[3:]
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


@router.callback_query(F.data.startswith("tg:"), TeaSessionFlow.tags)
async def tea_session_tags(callback: CallbackQuery, state: FSMContext) -> None:
    tag = callback.data[3:]
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
        private=True,
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

    blocks = ["📚 <b>Последние чаепития:</b>\n"]
    for s in sessions:
        line = f"<b>{s.session_date:%d.%m.%Y}</b> {_type_label(s.tea_type)} <b>{esc(s.tea_name)}</b>"
        if s.rating:
            line += f" — ⭐ {s.rating}/10"
        if s.taste_tags:
            line += f"\n    👅 {esc(s.taste_tags)}"
        if s.notes:
            preview = s.notes[:120] + ("…" if len(s.notes) > 120 else "")
            line += f"\n    📝 <i>{esc(preview)}</i>"
        if s.cha_qi and s.cha_qi != "none":
            qi = CHA_QI_OPTIONS.get(s.cha_qi, s.cha_qi)
            line += f"\n    ✨ {qi}"
        blocks.append(line)

    text = "\n\n".join(blocks)
    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>…показаны не все записи</i>"

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="go:tea")
    await callback.message.answer(text, reply_markup=kb.as_markup())

    for s in sessions:
        if s.photo_file_ids:
            fids = s.photo_file_ids.split(",")
            for fid in fids[:1]:
                try:
                    await callback.message.answer_photo(fid)
                except Exception:
                    pass
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
