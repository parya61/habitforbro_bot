"""Import T-Bank PDF statements from /tmp/расходы/."""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from db.database import get_session, init_db
from db.queries import get_user_by_tg
from db.finance_queries import check_duplicate, get_category_by_name, match_merchant, bulk_add_transactions
from db.models import FinTransaction
from config import config
from services.csv_import import parse_tbank_pdf, ImportResult, format_import_summary
from services.finance import ensure_seeded

IMPORT_DIR = Path("/tmp/расходы")

ACCOUNT_MAP = {
    "кредитка.pdf": "credit",
    "мо дебетовая.pdf": "debit",
    "общий с женой счет.pdf": "family",
}


async def import_pdf(pdf_path: Path, account: str):
    raw = pdf_path.read_bytes()
    rows, parse_errors = parse_tbank_pdf(raw)

    print(f"\n{'='*60}")
    print(f"Файл: {pdf_path.name} (account={account})")
    print(f"Распознано строк: {len(rows)}, ошибок парсинга: {len(parse_errors)}")

    if parse_errors:
        for e in parse_errors[:3]:
            print(f"  ERR: {e}")

    if not rows:
        print("  Нет операций для импорта.")
        return

    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            print("Admin user not found!")
            return

        await ensure_seeded(session, user.id)

        result = ImportResult()
        cat_cache = {}
        to_add = []

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
                account=account,
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
            await bulk_add_transactions(session, to_add)

        result.imported = len(to_add)
        result.errors = len(parse_errors)

        # Print summary (strip HTML tags)
        import re
        summary = format_import_summary(result)
        summary = re.sub(r"<[^>]+>", "", summary)
        print(summary)


async def main():
    await init_db()

    pdfs = sorted(IMPORT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {IMPORT_DIR}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF files")

    for pdf in pdfs:
        account = ACCOUNT_MAP.get(pdf.name, "debit")
        await import_pdf(pdf, account)

    print(f"\n{'='*60}")
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
