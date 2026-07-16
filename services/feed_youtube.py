"""YouTube feed: RSS monitor + transcript extraction."""
from __future__ import annotations

import logging
import re
from datetime import datetime

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

log = logging.getLogger(__name__)

YT_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YT_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:channel/|@)|youtube\.com/feeds/videos\.xml\?channel_id=)"
    r"([\w-]+)"
)


def extract_channel_id(url_or_id: str) -> str | None:
    url_or_id = url_or_id.strip()
    if re.match(r"^UC[\w-]{22}$", url_or_id):
        return url_or_id
    m = _YT_ID_RE.search(url_or_id)
    return m.group(1) if m else None


def fetch_rss(channel_id: str, max_items: int = 10) -> list[dict]:
    import urllib.request

    url = YT_RSS.format(channel_id=channel_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
        feed = feedparser.parse(xml_data)
    except Exception as exc:
        log.warning("RSS fetch failed for %s: %s", channel_id, exc)
        return []

    results = []
    for entry in feed.entries[:max_items]:
        video_id = entry.get("yt_videoid", "")
        if not video_id:
            link = entry.get("link", "")
            m = re.search(r"v=([\w-]+)", link)
            video_id = m.group(1) if m else ""

        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6])

        results.append({
            "video_id": video_id,
            "title": entry.get("title", ""),
            "url": YT_VIDEO_URL.format(video_id=video_id),
            "published": published,
            "author": entry.get("author", feed.feed.get("title", "")),
        })

    return results


def get_transcript(video_id: str, langs: tuple[str, ...] = ("ru", "en")) -> str | None:
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=list(langs))
        lines = [snippet.text for snippet in transcript.snippets]
        text = " ".join(lines)
        if len(text) > 15000:
            text = text[:15000] + "..."
        return text
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception as exc:
        log.warning("Transcript error for %s: %s", video_id, exc)
        return None


def fetch_channel_title(channel_id: str) -> str:
    import urllib.request

    url = YT_RSS.format(channel_id=channel_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
        feed = feedparser.parse(xml_data)
        return feed.feed.get("title", channel_id)
    except Exception:
        return channel_id
