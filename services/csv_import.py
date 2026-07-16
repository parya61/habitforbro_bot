"""Import T-Bank PDF/CSV exports into FinTransaction."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime


TBANK_CAT_MAP: dict[str, tuple[str, str]] = {
    # T-Bank category → (our category name, tx_type)
    "Супермаркеты": ("Продукты", "expense"),
    "Рестораны": ("Кафе", "expense"),
    "Фастфуд": ("Кафе", "expense"),
    "Транспорт": ("Транспорт", "expense"),
    "Такси": ("Транспорт", "expense"),
    "Топливо": ("Авто", "expense"),
    "Автоуслуги": ("Авто", "expense"),
    "Связь": ("Связь и подписки", "expense"),
    "Мобильная связь": ("Связь и подписки", "expense"),
    "Аптеки": ("Здоровье", "expense"),
    "Красота": ("Спорт и уход", "expense"),
    "Одежда и обувь": ("Одежда", "expense"),
    "Одежда/обувь": ("Одежда", "expense"),
    "Образование": ("Образование", "expense"),
    "Дом и ремонт": ("ЖКХ", "expense"),
    "Коммунальные услуги": ("ЖКХ", "expense"),
    "Цветы": ("Подарки", "expense"),
    "Спорттовары": ("Спорт и уход", "expense"),
    "Фитнес": ("Спорт и уход", "expense"),
    "Маркетплейсы": ("Маркетплейсы", "expense"),
    "Электроника": ("Маркетплейсы", "expense"),
    "Животные": ("Прочее", "expense"),
    "Развлечения": ("Прочее", "expense"),
    "Госуслуги": ("Прочее", "expense"),
    "Сервис": ("Прочее", "expense"),
    "Отели": ("Прочее", "expense"),
    "Турагентства": ("Прочее", "expense"),
    "Искусство": ("Прочее", "expense"),
    "Книги": ("Образование", "expense"),
    "Ж/д билеты": ("Транспорт", "expense"),
    "Авиабилеты": ("Транспорт", "expense"),
    "Музыка": ("Связь и подписки", "expense"),
    "Кино": ("Связь и подписки", "expense"),
    "Другое": ("Прочее", "expense"),
    "Различные товары": ("Прочее", "expense"),
    "Переводы": ("Переводы", "expense"),
    "Наличные": ("Переводы", "expense"),
    # Income
    "Зарплата": ("Зарплата", "income"),
    "Пополнения": ("Прочий доход", "income"),
    "Кэшбэк": ("Кэшбэк", "income"),
    "Бонусы": ("Кэшбэк", "income"),
    "Проценты на остаток": ("Инвестиции", "income"),
    "Процент на остаток": ("Инвестиции", "income"),
    "Инвестиции": ("Инвестиции", "income"),
    "Внесение наличных": ("Прочий доход", "income"),
}

DATE_FORMATS = ["%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%d.%m.%y"]


@dataclass
class TxRow:
    tx_date: date
    amount: float
    tx_type: str
    tbank_category: str
    our_category: str
    merchant: str
    card: str = ""


@dataclass
class ImportResult:
    imported: int = 0
    skipped_dup: int = 0
    skipped_status: int = 0
    skipped_zero: int = 0
    errors: int = 0
    date_min: date | None = None
    date_max: date | None = None
    cat_summary: dict[str, int] = field(default_factory=dict)


def _parse_date(val: str) -> date | None:
    val = val.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(val: str) -> float | None:
    val = val.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    val = re.sub(r"[^\d.\-]", "", val)
    try:
        return float(val)
    except ValueError:
        return None


def _classify(raw_amount: float, tbank_cat: str) -> tuple[float, str, str]:
    if raw_amount < 0:
        amount = abs(raw_amount)
        mapping = TBANK_CAT_MAP.get(tbank_cat)
        if mapping:
            our_cat = mapping[0]
        else:
            our_cat = "Прочее"
        return amount, "expense", our_cat
    else:
        amount = raw_amount
        mapping = TBANK_CAT_MAP.get(tbank_cat)
        if mapping and mapping[1] == "income":
            our_cat = mapping[0]
        else:
            our_cat = "Прочий доход"
        return amount, "income", our_cat


# ---- CSV parsing ----

REQUIRED_CSV_COLS = {"Дата платежа", "Сумма платежа", "Статус", "Описание"}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def parse_tbank_csv(raw: bytes) -> tuple[list[TxRow], list[str]]:
    text = _decode(raw)
    lines = text.splitlines()
    if not lines:
        return [], ["Файл пуст"]

    sep = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=sep)

    if not reader.fieldnames:
        return [], ["Не удалось прочитать заголовки CSV"]

    fields = set(reader.fieldnames)
    missing = REQUIRED_CSV_COLS - fields
    if missing:
        return [], [f"Отсутствуют колонки: {', '.join(sorted(missing))}"]

    rows: list[TxRow] = []
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        status = (row.get("Статус") or "").strip()
        if status != "OK":
            continue

        date_val = row.get("Дата платежа") or row.get("Дата операции") or ""
        tx_date = _parse_date(date_val)
        if tx_date is None:
            errors.append(f"Строка {i}: дата '{date_val}'")
            continue

        raw_amount = _parse_amount(row.get("Сумма платежа") or "0")
        if raw_amount is None or raw_amount == 0:
            continue

        tbank_cat = (row.get("Категория") or "Другое").strip()
        merchant = (row.get("Описание") or "").strip()
        card = (row.get("Номер карты") or "").strip()

        amount, tx_type, our_cat = _classify(raw_amount, tbank_cat)

        rows.append(TxRow(
            tx_date=tx_date, amount=amount, tx_type=tx_type,
            tbank_category=tbank_cat, our_category=our_cat,
            merchant=merchant, card=card,
        ))

    return rows, errors


# ---- PDF parsing ----

def parse_tbank_pdf(raw: bytes) -> tuple[list[TxRow], list[str]]:
    try:
        import pdfplumber
    except ImportError:
        return [], ["pdfplumber не установлен"]

    rows: list[TxRow] = []
    errors: list[str] = []

    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as exc:
        return [], [f"Не удалось открыть PDF: {exc}"]

    all_text = ""
    tables = []
    for page in pdf.pages:
        page_tables = page.extract_tables()
        if page_tables:
            tables.extend(page_tables)
        text = page.extract_text() or ""
        all_text += text + "\n"

    pdf.close()

    if tables:
        rows, errors = _parse_pdf_tables(tables)
    if not rows:
        rows2, errors2 = _parse_pdf_text(all_text)
        if rows2:
            rows = rows2
            errors = errors2

    return rows, errors


def _normalize_header(h: str | None) -> str:
    if not h:
        return ""
    return re.sub(r"\s+", " ", h.strip().lower())


def _find_col(headers: list[str], *candidates: str) -> int | None:
    for i, h in enumerate(headers):
        norm = _normalize_header(h)
        for c in candidates:
            if c in norm:
                return i
    return None


def _parse_pdf_tables(tables: list[list[list[str | None]]]) -> tuple[list[TxRow], list[str]]:
    rows: list[TxRow] = []
    errors: list[str] = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        header_row = [_normalize_header(c) for c in table[0]]

        date_col = _find_col(header_row, "дата опер", "дата плат", "дата")
        amount_col = _find_col(header_row, "сумма плат", "сумма опер", "сумма")
        desc_col = _find_col(header_row, "описан", "операц")
        cat_col = _find_col(header_row, "категор")
        status_col = _find_col(header_row, "статус")

        if date_col is None or amount_col is None:
            continue

        for ri, row in enumerate(table[1:], start=2):
            if not row or len(row) <= max(date_col, amount_col):
                continue

            if status_col is not None and len(row) > status_col:
                st = (row[status_col] or "").strip()
                if st and st != "OK":
                    continue

            date_str = (row[date_col] or "").strip()
            if not date_str:
                continue
            date_str = date_str.split("\n")[0].strip()
            tx_date = _parse_date(date_str)
            if tx_date is None:
                continue

            amount_str = (row[amount_col] or "").strip()
            if not amount_str:
                continue
            raw_amount = _parse_amount(amount_str)
            if raw_amount is None or raw_amount == 0:
                continue

            merchant = ""
            if desc_col is not None and len(row) > desc_col:
                merchant = (row[desc_col] or "").strip().replace("\n", " ")

            tbank_cat = "Другое"
            if cat_col is not None and len(row) > cat_col:
                tbank_cat = (row[cat_col] or "Другое").strip()

            amount, tx_type, our_cat = _classify(raw_amount, tbank_cat)

            rows.append(TxRow(
                tx_date=tx_date, amount=amount, tx_type=tx_type,
                tbank_category=tbank_cat, our_category=our_cat,
                merchant=merchant,
            ))

    return rows, errors


_PDF_LINE_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{2,4})"    # date
    r"\s+"
    r"(.+?)"                       # description
    r"\s+"
    r"([+-]?\s*[\d\s]+[.,]?\d*)"   # amount
)


def _parse_pdf_text(text: str) -> tuple[list[TxRow], list[str]]:
    rows: list[TxRow] = []
    errors: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = _PDF_LINE_RE.search(line)
        if not m:
            continue

        tx_date = _parse_date(m.group(1))
        if tx_date is None:
            continue

        raw_amount = _parse_amount(m.group(3))
        if raw_amount is None or raw_amount == 0:
            continue

        merchant = m.group(2).strip()

        amount, tx_type, our_cat = _classify(raw_amount, "Другое")

        rows.append(TxRow(
            tx_date=tx_date, amount=amount, tx_type=tx_type,
            tbank_category="Другое", our_category=our_cat,
            merchant=merchant,
        ))

    return rows, errors


def format_import_summary(result: ImportResult) -> str:
    parts = [f"📥 <b>Импорт завершён</b>\n"]

    if result.date_min and result.date_max:
        parts.append(
            f"📅 Период: {result.date_min:%d.%m.%Y} — {result.date_max:%d.%m.%Y}"
        )

    parts.append(f"✅ Импортировано: <b>{result.imported}</b>")

    if result.skipped_dup:
        parts.append(f"🔄 Дубликаты: {result.skipped_dup}")
    if result.skipped_zero:
        parts.append(f"⏭ Нулевые суммы: {result.skipped_zero}")
    if result.errors:
        parts.append(f"❌ Ошибки парсинга: {result.errors}")

    if result.cat_summary:
        parts.append("\n<b>По категориям:</b>")
        for cat, cnt in sorted(result.cat_summary.items(), key=lambda x: -x[1]):
            parts.append(f"  {cat}: {cnt}")

    return "\n".join(parts)
