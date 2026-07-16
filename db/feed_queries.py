"""Queries for feed aggregator (Telegram channels, YouTube)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import FeedItem, FeedSource


# ---------- Sources ----------

async def add_source(
    session: AsyncSession,
    user_id: int,
    source_type: str,
    source_id: str,
    title: str,
) -> FeedSource:
    src = FeedSource(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
    )
    session.add(src)
    await session.commit()
    await session.refresh(src)
    return src


async def list_sources(
    session: AsyncSession, user_id: int, source_type: str | None = None
) -> list[FeedSource]:
    stmt = select(FeedSource).where(
        FeedSource.user_id == user_id, FeedSource.active == True  # noqa: E712
    )
    if source_type:
        stmt = stmt.where(FeedSource.source_type == source_type)
    stmt = stmt.order_by(FeedSource.created_at)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_source(session: AsyncSession, source_id: int) -> FeedSource | None:
    res = await session.execute(
        select(FeedSource).where(FeedSource.id == source_id)
    )
    return res.scalar_one_or_none()


async def toggle_source(session: AsyncSession, source_id: int) -> bool:
    src = await get_source(session, source_id)
    if not src:
        return False
    src.active = not src.active
    await session.commit()
    return True


async def delete_source(session: AsyncSession, source_id: int) -> bool:
    src = await get_source(session, source_id)
    if not src:
        return False
    await session.delete(src)
    await session.commit()
    return True


async def update_last_checked(
    session: AsyncSession, source_id: int
) -> None:
    src = await get_source(session, source_id)
    if src:
        src.last_checked = datetime.utcnow()
        await session.commit()


# ---------- Items ----------

async def item_exists(
    session: AsyncSession, source_id: int, external_id: str
) -> bool:
    cnt = await session.scalar(
        select(func.count()).select_from(FeedItem).where(
            FeedItem.source_id == source_id,
            FeedItem.external_id == external_id,
        )
    )
    return (cnt or 0) > 0


async def add_item(
    session: AsyncSession,
    source_id: int,
    item_type: str,
    external_id: str,
    title: str | None = None,
    text: str | None = None,
    url: str | None = None,
    published_at: datetime | None = None,
) -> FeedItem:
    item = FeedItem(
        source_id=source_id,
        item_type=item_type,
        external_id=external_id,
        title=title,
        text=text,
        url=url,
        published_at=published_at,
    )
    session.add(item)
    await session.commit()
    return item


async def add_items_bulk(
    session: AsyncSession, items: list[FeedItem]
) -> int:
    for item in items:
        session.add(item)
    await session.commit()
    return len(items)


async def recent_items(
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
    source_type: str | None = None,
) -> list[FeedItem]:
    stmt = (
        select(FeedItem)
        .join(FeedSource)
        .options(joinedload(FeedItem.source))
        .where(FeedSource.user_id == user_id, FeedSource.active == True)  # noqa: E712
    )
    if source_type:
        stmt = stmt.where(FeedSource.source_type == source_type)
    stmt = stmt.order_by(FeedItem.published_at.desc().nullslast()).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def count_items_by_source(
    session: AsyncSession, source_id: int
) -> int:
    cnt = await session.scalar(
        select(func.count()).select_from(FeedItem).where(
            FeedItem.source_id == source_id
        )
    )
    return cnt or 0


async def search_items(
    session: AsyncSession,
    user_id: int,
    query: str,
    limit: int = 10,
) -> list[FeedItem]:
    pattern = f"%{query}%"
    stmt = (
        select(FeedItem)
        .join(FeedSource)
        .options(joinedload(FeedItem.source))
        .where(
            FeedSource.user_id == user_id,
            (FeedItem.title.ilike(pattern) | FeedItem.text.ilike(pattern)),
        )
        .order_by(FeedItem.published_at.desc().nullslast())
        .limit(limit)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())
