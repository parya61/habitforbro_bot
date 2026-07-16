"""Feed aggregator: periodic check for new content from all sources."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from db.feed_queries import (
    add_item,
    item_exists,
    list_sources,
    update_last_checked,
)
from db.models import FeedItem

log = logging.getLogger(__name__)


async def fetch_youtube_source(session: AsyncSession, source) -> int:
    from services.feed_youtube import fetch_rss, get_transcript

    videos = fetch_rss(source.source_id, max_items=5)
    added = 0

    for video in videos:
        vid = video["video_id"]
        if not vid:
            continue
        if await item_exists(session, source.id, vid):
            continue

        transcript = get_transcript(vid)
        title = video.get("title", "")

        text_parts = []
        if title:
            text_parts.append(title)
        if transcript:
            text_parts.append(transcript)

        await add_item(
            session,
            source_id=source.id,
            item_type="video",
            external_id=vid,
            title=title,
            text="\n\n".join(text_parts) if text_parts else None,
            url=video.get("url"),
            published_at=video.get("published"),
        )
        added += 1
        log.info("YouTube: +%s (%s)", title[:60], source.title)

    await update_last_checked(session, source.id)
    return added


async def fetch_telegram_source(session: AsyncSession, source) -> int:
    from services.feed_telegram import read_channel_posts

    min_date = source.last_checked or (datetime.utcnow() - timedelta(days=3))

    try:
        posts = await read_channel_posts(
            source.source_id, limit=20, min_date=min_date
        )
    except Exception as exc:
        log.error("Telegram fetch error for %s: %s", source.source_id, exc)
        return 0

    added = 0
    for post in posts:
        mid = post["message_id"]
        if await item_exists(session, source.id, mid):
            continue

        text = post.get("text", "")
        title = text[:120].split("\n")[0] if text else None

        await add_item(
            session,
            source_id=source.id,
            item_type="post",
            external_id=mid,
            title=title,
            text=text,
            url=post.get("url"),
            published_at=post.get("date"),
        )
        added += 1

    await update_last_checked(session, source.id)
    if added:
        log.info("Telegram: +%d from %s", added, source.title)
    return added


async def run_feed_check(session: AsyncSession, user_id: int) -> dict[str, int]:
    sources = await list_sources(session, user_id)
    results = {"youtube": 0, "telegram": 0}

    for src in sources:
        try:
            if src.source_type == "youtube":
                results["youtube"] += await fetch_youtube_source(session, src)
            elif src.source_type == "telegram":
                results["telegram"] += await fetch_telegram_source(session, src)
        except Exception as exc:
            log.error("Feed check error for %s (%s): %s", src.title, src.source_type, exc)

    return results
