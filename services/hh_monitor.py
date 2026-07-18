"""Vacancy monitor for MLSecOps / AI Security positions.

Sources: hh.ru (RSS), career.habr.com (HTML scraping).
hh.ru API is geo-blocked from abroad, so we use RSS feeds instead.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from xml.etree import ElementTree

import aiohttp

logger = logging.getLogger("habits-bot")

SEEN_FILE = Path(__file__).resolve().parent.parent / "data" / "hh_seen.json"

HH_RSS = "https://hh.ru/search/vacancy/rss"
HABR_URL = "https://career.habr.com/vacancies"

HH_QUERIES = [
    "MLSecOps",
    "AI Security",
    "LLM Security",
    "безопасность ИИ",
    "ML Security",
    "безопасность машинного обучения",
    "защита LLM",
    "AI Red Team",
    "информационная безопасность ML",
    "DevSecOps AI",
]

HABR_QUERIES = [
    "AI Security",
    "MLSecOps",
    "безопасность ИИ",
    "LLM Security",
]

RELEVANT_KEYWORDS = re.compile(
    r"security|безопасн|защит|ИБ|secops|mlsecops|llm|ml.engineer|"
    r"ai.engineer|red.team|soc|pentest|пентест|dlp|siem|"
    r"machine.learning|искусственн|нейросет|deep.learning|"
    r"devsecops|appsec|prompt.injection|adversarial",
    re.IGNORECASE,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HabitBot/1.0)"}


def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_seen(ids: set[str]) -> None:
    trimmed = sorted(ids)[-1000:]
    SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


def _is_relevant(title: str) -> bool:
    return bool(RELEVANT_KEYWORDS.search(title))


async def _fetch_hh_rss(session: aiohttp.ClientSession, query: str) -> list[dict]:
    params = {"text": query, "area": "1", "items_on_page": "20"}
    results = []
    try:
        async with session.get(HH_RSS, params=params, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            xml_text = await resp.text()
    except Exception as exc:
        logger.warning("HH RSS | Query %r failed: %s", query, exc)
        return results

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return results

    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""

        company_m = re.search(r"Вакансия компании:\s*(.+?)(?:<|$)", desc)
        company = company_m.group(1).strip() if company_m else "?"

        salary_m = re.search(r"месячного дохода:\s*(.+?)(?:<|$)", desc)
        salary = salary_m.group(1).strip() if salary_m else ""
        if salary == "не указан":
            salary = ""

        region_m = re.search(r"Регион:\s*(.+?)(?:<|$)", desc)
        region = region_m.group(1).strip() if region_m else ""

        vid = re.search(r"/vacancy/(\d+)", link)
        uid = f"hh_{vid.group(1)}" if vid else f"hh_{hash(link)}"

        results.append({
            "id": uid,
            "title": title,
            "employer": company,
            "area": region,
            "salary": salary,
            "url": link,
            "source": "hh.ru",
        })

    return results


async def _fetch_habr(session: aiohttp.ClientSession, query: str) -> list[dict]:
    params = {"q": query, "type": "all"}
    results = []
    try:
        async with session.get(HABR_URL, params=params, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()
    except Exception as exc:
        logger.warning("HABR | Query %r failed: %s", query, exc)
        return results

    for m in re.finditer(
        r'<a\s+class="vacancy-card__title-link"\s+href="(/vacancies/(\d+))">([^<]+)</a>',
        html,
    ):
        path, vid, title = m.group(1), m.group(2), m.group(3).strip()
        uid = f"habr_{vid}"

        company = ""
        comp_pattern = rf'href="/companies/[^"]*"[^>]*class="[^"]*vacancy-card__company-title[^"]*"[^>]*>([^<]+)</a>'
        comp_matches = list(re.finditer(comp_pattern, html[m.start():m.start() + 2000]))
        if comp_matches:
            company = comp_matches[0].group(1).strip()

        results.append({
            "id": uid,
            "title": title,
            "employer": company or "?",
            "area": "",
            "salary": "",
            "url": f"https://career.habr.com{path}",
            "source": "habr",
        })

    return results


async def check_vacancies() -> list[dict]:
    seen = _load_seen()
    all_vacancies: dict[str, dict] = {}

    async with aiohttp.ClientSession() as session:
        for query in HH_QUERIES:
            items = await _fetch_hh_rss(session, query)
            for v in items:
                if v["id"] not in seen and v["id"] not in all_vacancies:
                    if _is_relevant(v["title"]):
                        all_vacancies[v["id"]] = v

        for query in HABR_QUERIES:
            items = await _fetch_habr(session, query)
            for v in items:
                if v["id"] not in seen and v["id"] not in all_vacancies:
                    if _is_relevant(v["title"]):
                        all_vacancies[v["id"]] = v

    new_list = list(all_vacancies.values())
    seen.update(all_vacancies.keys())
    _save_seen(seen)

    return new_list


def format_vacancies(vacancies: list[dict]) -> str:
    if not vacancies:
        return (
            "🔍 <b>Мониторинг вакансий — AI/ML Security</b>\n\n"
            "За последние дни новых вакансий по защите ИИ / MLSecOps "
            "не появилось. Рынок тихий, но я слежу 👀"
        )

    lines = [f"🔍 <b>Мониторинг вакансий — AI/ML Security</b>\n"]
    lines.append(f"Найдено <b>{len(vacancies)}</b> новых:\n")

    for v in vacancies[:15]:
        sal = f" | {v['salary']}" if v.get("salary") else ""
        area = f", {v['area']}" if v.get("area") else ""
        src = f" [{v['source']}]"
        lines.append(
            f"▫️ <b>{v['title']}</b>\n"
            f"  {v['employer']}{area}{sal}{src}\n"
            f"  {v['url']}\n"
        )

    if len(vacancies) > 15:
        lines.append(f"\n...и ещё {len(vacancies) - 15}")

    return "\n".join(lines)
