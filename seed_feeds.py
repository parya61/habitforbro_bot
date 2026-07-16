"""Seed feed sources from user's channel lists. Run once."""
import asyncio
import re
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from db.database import get_session, init_db
from db.feed_queries import add_source, list_sources
from db.queries import get_user_by_tg
from config import config

YOUTUBE_HANDLES = [
    "3blue1brown",
    "mikhaylovgleb",
    "mouse-ml",
    "MLSecOpsCommunity",
    "AntiMalwarerus",
    "Deeplearningai",
    "YandexforDevelopers",
    "YandexforML",
    "Yandex4Analytics",
    "AndreySozykin",
    "positiveevents5242",
    "lectory_fpmi",
]

TELEGRAM_CHANNELS = [
    "borismlsec",
    "mlsecfeed",
    "ml_ops",
    "poxek_ai",
    "machinelearning_interview",
    "infosec_work",
]


async def resolve_yt_channel_id(handle: str) -> tuple[str | None, str]:
    """Fetch YouTube channel page and extract channel ID."""
    url = f"https://www.youtube.com/@{handle}"
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    print(f"  WARN: {handle} -> HTTP {resp.status}")
                    return None, handle
                text = await resp.text()

        m = re.search(r'"channelId"\s*:\s*"(UC[\w-]+)"', text)
        if not m:
            m = re.search(r'channel/(UC[\w-]+)', text)
        channel_id = m.group(1) if m else None

        m2 = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        if not m2:
            m2 = re.search(r'<title>([^<]+)</title>', text)
        title = m2.group(1).replace(" - YouTube", "").strip() if m2 else handle

        return channel_id, title
    except Exception as exc:
        print(f"  ERROR: {handle} -> {exc}")
        return None, handle


async def main():
    await init_db()

    async with get_session() as session:
        user = await get_user_by_tg(session, config.admin_id)
        if not user:
            print("Admin user not found!")
            sys.exit(1)

        existing = await list_sources(session, user.id)
        existing_ids = {s.source_id for s in existing}

        print(f"User: {user.name} (id={user.id})")
        print(f"Existing sources: {len(existing)}")

        # YouTube
        print(f"\n=== YouTube ({len(YOUTUBE_HANDLES)} channels) ===")
        for handle in YOUTUBE_HANDLES:
            channel_id, title = await resolve_yt_channel_id(handle)
            if not channel_id:
                print(f"  SKIP: @{handle} - could not resolve channel ID")
                continue
            if channel_id in existing_ids:
                print(f"  EXISTS: {title} ({channel_id})")
                continue
            await add_source(session, user.id, "youtube", channel_id, title)
            existing_ids.add(channel_id)
            print(f"  ADDED: {title} ({channel_id})")

        # Telegram
        print(f"\n=== Telegram ({len(TELEGRAM_CHANNELS)} channels) ===")
        for username in TELEGRAM_CHANNELS:
            if username in existing_ids:
                print(f"  EXISTS: @{username}")
                continue
            await add_source(session, user.id, "telegram", username, f"@{username}")
            existing_ids.add(username)
            print(f"  ADDED: @{username}")

        final = await list_sources(session, user.id)
        print(f"\nTotal sources: {len(final)}")


if __name__ == "__main__":
    asyncio.run(main())
