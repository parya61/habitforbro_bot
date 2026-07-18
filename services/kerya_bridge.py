"""Мост к Кере (OpenClaw) — единый мозг для умных рассылок.

Бот не думает сам: для админских разборов он просит Керю (у которой память,
философия и живой доступ к данным) и лишь доставляет её ответ в Telegram.
Fallback на прямой DeepSeek-вызов остаётся на стороне вызывающего кода.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger("habits-bot")

TIMEOUT_SEC = 240


def _extract_text(obj) -> str | None:
    """Достаёт первый payloads[].text из ответа openclaw agent --json."""
    if isinstance(obj, dict):
        payloads = obj.get("payloads")
        if isinstance(payloads, list):
            for p in payloads:
                if isinstance(p, dict) and p.get("text"):
                    return p["text"]
        for v in obj.values():
            found = _extract_text(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_text(v)
            if found:
                return found
    return None


def _md_to_html(text: str) -> str:
    """Минимальная конвертация markdown Кери в Telegram-HTML."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


async def ask_kerya(prompt: str, timeout: int = TIMEOUT_SEC) -> str | None:
    """Один ход Кери через openclaw agent CLI. None при любом сбое."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-u", "clawd",
            "openclaw", "agent", "--agent", "main", "--json", "-m", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            logger.error("KERYA | agent exited %s", proc.returncode)
            return None
        data = json.loads(out.decode("utf-8", errors="replace"))
        text = _extract_text(data)
        if not text:
            logger.error("KERYA | no text in agent reply")
            return None
        logger.info("KERYA | reply ok (%d chars)", len(text))
        return _md_to_html(text.strip())
    except asyncio.TimeoutError:
        logger.error("KERYA | timeout after %ss", timeout)
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.error("KERYA | bridge failed: %s", exc)
        return None
