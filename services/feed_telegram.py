"""Telegram channel reader via Telethon."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

SESSION_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "telethon.session")


def _get_client():
    from telethon import TelegramClient

    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")

    if not api_id or not api_hash:
        raise RuntimeError(
            "TG_API_ID and TG_API_HASH must be set. "
            "Get them at https://my.telegram.org/apps"
        )

    return TelegramClient(SESSION_PATH, int(api_id), api_hash)


async def read_channel_posts(
    channel_username: str,
    limit: int = 20,
    min_date: datetime | None = None,
) -> list[dict]:
    client = _get_client()
    await client.connect()

    if not await client.is_user_authorized():
        log.error("Telethon not authorized. Run auth_telethon.py first.")
        await client.disconnect()
        return []

    try:
        entity = await client.get_entity(channel_username)
    except Exception as exc:
        log.error("Cannot resolve channel %s: %s", channel_username, exc)
        await client.disconnect()
        return []

    posts = []
    async for msg in client.iter_messages(entity, limit=limit):
        if min_date and msg.date.replace(tzinfo=None) < min_date:
            break

        text = msg.text or ""
        if not text and msg.message:
            text = msg.message

        if not text.strip():
            continue

        posts.append({
            "message_id": str(msg.id),
            "text": text[:10000],
            "date": msg.date.replace(tzinfo=None),
            "url": f"https://t.me/{channel_username}/{msg.id}",
        })

    await client.disconnect()
    return posts


async def resolve_channel_title(channel_username: str) -> str | None:
    client = _get_client()
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        return None

    try:
        entity = await client.get_entity(channel_username)
        title = getattr(entity, "title", None) or channel_username
    except Exception:
        title = None

    await client.disconnect()
    return title
