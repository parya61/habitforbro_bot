#!/usr/bin/env python3
"""habits-query — read-only CLI access to habits.db for Kerya (OpenClaw agent).

Usage:
  habits-query birthdays [days=60]     upcoming birthdays with age and gift ideas
  habits-query gifts [person]          gift ideas, optionally filtered by person name
  habits-query finance [YYYY-MM]       month summary by category (default: current)
  habits-query habits                  active habits with today's status
  habits-query goals [level]           goals (life/year/month/tomorrow), default all
  habits-query diary [n=7]             last n diary entries
  habits-query tea                     tea collection + last sessions
  habits-query grocery                 grocery list due items
  habits-query cafe                    cafe places (visited + wishlist)
  habits-query trips                   active trips with checklists
  habits-query feeds [n=10]            recent feed items
  habits-query schema                  table list with columns
  habits-query sql "SELECT ..."        arbitrary SELECT (read-only enforced)

Output: JSON (ensure_ascii=False). DB opened in read-only mode — writes impossible.
"""
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta

DB = "file:/data/habits.db?mode=ro"
ADMIN_TG = 632286233


def con():
    # mode=ro + busy_timeout: honest WAL reads that wait out concurrent writes.
    # Never use immutable=1 here — the bot writes to this DB continuously.
    c = sqlite3.connect(DB, uri=True, timeout=5)
    c.execute("PRAGMA busy_timeout=5000")
    c.row_factory = sqlite3.Row
    return c


def rows_to_list(rows):
    return [dict(r) for r in rows]


def admin_user_id(c):
    r = c.execute("SELECT id FROM users WHERE telegram_id=?", (ADMIN_TG,)).fetchone()
    return r["id"] if r else 1


def out(data):
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))


def cmd_birthdays(args):
    days = int(args[0]) if args else 60
    c = con()
    uid = admin_user_id(c)
    today = date.today()
    result = []
    for p in c.execute(
        "SELECT id, name, birthday, rel_type, notes FROM persons "
        "WHERE user_id=? AND birthday IS NOT NULL", (uid,)
    ):
        try:
            bd = datetime.strptime(p["birthday"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        nxt = bd.replace(year=today.year)
        if nxt < today:
            nxt = bd.replace(year=today.year + 1)
        delta = (nxt - today).days
        if delta <= days:
            gifts = rows_to_list(c.execute(
                "SELECT title, status, price_estimate, event FROM gift_ideas "
                "WHERE person_id=?", (p["id"],)
            ))
            result.append({
                "name": p["name"], "rel_type": p["rel_type"],
                "birthday": p["birthday"], "in_days": delta,
                "turns_age": nxt.year - bd.year,
                "gift_ideas": gifts, "notes": p["notes"],
            })
    result.sort(key=lambda x: x["in_days"])
    out(result)


def cmd_gifts(args):
    c = con()
    uid = admin_user_id(c)
    q = (
        "SELECT g.title, g.status, g.price_estimate, g.event, g.notes, "
        "p.name AS person, p.birthday FROM gift_ideas g "
        "LEFT JOIN persons p ON p.id = g.person_id WHERE g.user_id=?"
    )
    params = [uid]
    if args:
        q += " AND p.name LIKE ?"
        params.append(f"%{args[0]}%")
    out(rows_to_list(c.execute(q, params)))


def cmd_finance(args):
    month = args[0] if args else date.today().strftime("%Y-%m")
    c = con()
    uid = admin_user_id(c)
    cats = rows_to_list(c.execute(
        "SELECT fc.name AS category, fc.cat_type, "
        "ROUND(SUM(t.amount), 2) AS total, COUNT(*) AS n "
        "FROM fin_transactions t LEFT JOIN fin_categories fc ON fc.id=t.category_id "
        "WHERE t.user_id=? AND strftime('%Y-%m', t.tx_date)=? "
        "GROUP BY fc.name, fc.cat_type ORDER BY total DESC", (uid, month)
    ))
    totals = rows_to_list(c.execute(
        "SELECT tx_type, ROUND(SUM(amount),2) AS total FROM fin_transactions "
        "WHERE user_id=? AND strftime('%Y-%m', tx_date)=? GROUP BY tx_type",
        (uid, month)
    ))
    out({"month": month, "totals": totals, "by_category": cats})


def cmd_habits(_args):
    c = con()
    uid = admin_user_id(c)
    today = date.today().isoformat()
    out(rows_to_list(c.execute(
        "SELECT h.title, h.emoji, h.frequency, h.remind_time, "
        "COALESCE(l.done, 0) AS done_today "
        "FROM habits h LEFT JOIN habit_logs l "
        "ON l.habit_id=h.id AND l.log_date=? "
        "WHERE h.user_id=? AND h.status='active'", (today, uid)
    )))


def cmd_goals(args):
    c = con()
    uid = admin_user_id(c)
    q = "SELECT level, title, status, created_at, achieved_at FROM goals WHERE user_id=?"
    params = [uid]
    if args:
        q += " AND level=?"
        params.append(args[0])
    q += " ORDER BY level, created_at"
    out(rows_to_list(c.execute(q, params)))


def cmd_diary(args):
    n = int(args[0]) if args else 7
    c = con()
    uid = admin_user_id(c)
    out(rows_to_list(c.execute(
        "SELECT entry_date, mood, text FROM diary_entries "
        "WHERE user_id=? ORDER BY entry_date DESC LIMIT ?", (uid, n)
    )))


def cmd_tea(_args):
    c = con()
    uid = admin_user_id(c)
    collection = rows_to_list(c.execute(
        "SELECT tea_name, tea_type, remaining_grams, weight_grams, vendor, status "
        "FROM tea_collection WHERE user_id=? AND status='active'", (uid,)
    ))
    sessions = rows_to_list(c.execute(
        "SELECT session_date, tea_name, tea_type, rating, notes "
        "FROM tea_sessions WHERE user_id=? ORDER BY session_date DESC LIMIT 10",
        (uid,)
    ))
    out({"collection": collection, "recent_sessions": sessions})


def cmd_grocery(_args):
    c = con()
    uid = admin_user_id(c)
    out(rows_to_list(c.execute(
        "SELECT name, category, usual_store, last_bought, buy_freq_days, for_whom "
        "FROM grocery_items WHERE user_id=? AND active=1 "
        "AND (last_bought IS NULL OR date(last_bought, '+' || buy_freq_days || ' days') <= date('now'))",
        (uid,)
    )))


def cmd_cafe(_args):
    c = con()
    uid = admin_user_id(c)
    out(rows_to_list(c.execute(
        "SELECT p.name, p.cuisine, p.is_wishlist, p.notes, "
        "COUNT(v.id) AS visits, ROUND(AVG(v.rating),1) AS avg_rating "
        "FROM cafe_places p LEFT JOIN cafe_visits v ON v.cafe_id=p.id "
        "WHERE p.user_id=? GROUP BY p.id ORDER BY p.is_wishlist, visits DESC",
        (uid,)
    )))


def cmd_trips(_args):
    c = con()
    uid = admin_user_id(c)
    trips = rows_to_list(c.execute(
        "SELECT id, name, destination, start_date, end_date, status, notes "
        "FROM trips WHERE user_id=? AND status != 'done'", (uid,)
    ))
    for t in trips:
        t["checklist"] = rows_to_list(c.execute(
            "SELECT text, category, checked FROM checklist_items WHERE trip_id=?",
            (t["id"],)
        ))
    out(trips)


def cmd_feeds(args):
    n = int(args[0]) if args else 10
    c = con()
    out(rows_to_list(c.execute(
        "SELECT s.title AS source, i.title, i.url, i.published_at "
        "FROM feed_items i JOIN feed_sources s ON s.id=i.source_id "
        "ORDER BY i.published_at DESC LIMIT ?", (n,)
    )))


def cmd_schema(_args):
    c = con()
    result = {}
    for (name,) in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ):
        result[name] = [r[1] for r in c.execute(f"PRAGMA table_info({name})")]
    out(result)


FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|pragma|vacuum)\b",
    re.IGNORECASE,
)


def cmd_sql(args):
    if not args:
        print("usage: habits-query sql \"SELECT ...\"", file=sys.stderr)
        sys.exit(1)
    query = args[0]
    if not query.strip().lower().startswith("select") or FORBIDDEN.search(query):
        print("ERROR: only SELECT queries allowed", file=sys.stderr)
        sys.exit(1)
    c = con()
    out(rows_to_list(c.execute(query).fetchmany(200)))


COMMANDS = {
    "birthdays": cmd_birthdays, "gifts": cmd_gifts, "finance": cmd_finance,
    "habits": cmd_habits, "goals": cmd_goals, "diary": cmd_diary,
    "tea": cmd_tea, "grocery": cmd_grocery, "cafe": cmd_cafe,
    "trips": cmd_trips, "feeds": cmd_feeds, "schema": cmd_schema, "sql": cmd_sql,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"unknown command: {cmd}\n{__doc__}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
