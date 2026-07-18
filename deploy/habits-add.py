#!/usr/bin/env python3
"""habits-add — narrow write access to habits.db for Kerya (OpenClaw agent).

Only INSERT of finance transactions. No updates, no deletes, no other tables.

Usage:
  habits-add expense <сумма> <категория> [описание] [--date YYYY-MM-DD] [--account debit|credit|family]
  habits-add income <сумма> <категория> [описание] [--date YYYY-MM-DD] [--account ...]
  habits-add categories               list valid category names

Examples:
  habits-add expense 1543.50 Продукты "Пятёрочка"
  habits-add expense 4550 Чай "бо цзюнь 2022"
  habits-add income 87000 Зарплата --date 2026-07-10

Rules:
  - amount must be 0 < x <= 200000 (larger sums — only via the bot UI)
  - category must exist for the tx type (see: habits-add categories)
  - exact duplicate (same date+amount+merchant) is refused; add --force to override
  - every insert is appended to /opt/habits-bot/data/kerya-writes.log
"""
import json
import sqlite3
import sys
from datetime import date, datetime

DB = "/data/habits.db"
LOG = "/opt/habits-bot/data/kerya-writes.log"
ADMIN_TG = 632286233
MAX_AMOUNT = 200000
ACCOUNTS = {"debit", "credit", "family"}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return

    con = sqlite3.connect(DB, timeout=10)
    con.execute("PRAGMA busy_timeout=5000")
    con.row_factory = sqlite3.Row

    uid_row = con.execute(
        "SELECT id FROM users WHERE telegram_id=?", (ADMIN_TG,)
    ).fetchone()
    if not uid_row:
        fail("admin user not found")
    uid = uid_row["id"]

    if args[0] == "categories":
        rows = con.execute(
            "SELECT name, cat_type FROM fin_categories WHERE user_id=? "
            "ORDER BY cat_type, sort_order", (uid,)
        ).fetchall()
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1))
        return

    if args[0] not in ("expense", "income"):
        fail(f"unknown command: {args[0]}")

    tx_type = args[0]
    rest = args[1:]

    tx_date = date.today().isoformat()
    account = "debit"
    force = False
    positional = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--date":
            i += 1
            tx_date = rest[i]
        elif a == "--account":
            i += 1
            account = rest[i]
        elif a == "--force":
            force = True
        else:
            positional.append(a)
        i += 1

    if len(positional) < 2:
        fail("need: <amount> <category> [description]")

    try:
        amount = round(float(positional[0].replace(",", ".")), 2)
    except ValueError:
        fail(f"bad amount: {positional[0]}")
    if not (0 < amount <= MAX_AMOUNT):
        fail(f"amount out of range (0 < x <= {MAX_AMOUNT}) — крупные суммы только через бота")

    category_name = positional[1]
    merchant = " ".join(positional[2:]).strip() or None

    try:
        datetime.strptime(tx_date, "%Y-%m-%d")
    except ValueError:
        fail(f"bad date: {tx_date} (need YYYY-MM-DD)")
    if account not in ACCOUNTS:
        fail(f"bad account: {account} (need one of {sorted(ACCOUNTS)})")

    cat = con.execute(
        "SELECT id, name FROM fin_categories WHERE user_id=? AND cat_type=? "
        "AND lower(name)=lower(?)", (uid, tx_type, category_name)
    ).fetchone()
    if not cat:
        valid = [r["name"] for r in con.execute(
            "SELECT name FROM fin_categories WHERE user_id=? AND cat_type=?",
            (uid, tx_type)
        )]
        fail(f"category '{category_name}' not found for {tx_type}. Valid: {valid}")

    dup = con.execute(
        "SELECT id FROM fin_transactions WHERE user_id=? AND tx_date=? "
        "AND amount=? AND COALESCE(merchant,'')=COALESCE(?,'')",
        (uid, tx_date, amount, merchant)
    ).fetchone()
    if dup and not force:
        fail(f"duplicate of transaction id={dup['id']} — add --force if intentional")

    cur = con.execute(
        "INSERT INTO fin_transactions "
        "(user_id, amount, tx_type, category_id, merchant, account, tx_date, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'added by Kerya', ?)",
        (uid, amount, tx_type, cat["id"], merchant, account, tx_date,
         datetime.utcnow().isoformat(sep=" ", timespec="seconds")),
    )
    con.commit()
    tx_id = cur.lastrowid

    with open(LOG, "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.utcnow().isoformat()} INSERT id={tx_id} {tx_type} "
            f"{amount} {cat['name']} {merchant or ''} {tx_date} {account}\n"
        )

    print(json.dumps({
        "ok": True, "id": tx_id, "tx_type": tx_type, "amount": amount,
        "category": cat["name"], "merchant": merchant,
        "date": tx_date, "account": account,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
