"""Database queries for trip/checklist module."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import ChecklistItem, Trip


async def count_trips(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(Trip.id)).where(Trip.user_id == user_id)
    )
    return res.scalar() or 0


async def add_trip(
    session: AsyncSession,
    user_id: int,
    name: str,
    destination: str | None = None,
) -> Trip:
    trip = Trip(user_id=user_id, name=name, destination=destination)
    session.add(trip)
    await session.commit()
    return trip


async def get_trip(session: AsyncSession, trip_id: int) -> Trip | None:
    res = await session.execute(
        select(Trip)
        .options(selectinload(Trip.items))
        .where(Trip.id == trip_id)
    )
    return res.scalar_one_or_none()


async def list_trips(
    session: AsyncSession, user_id: int, active_only: bool = False,
) -> list[Trip]:
    q = (
        select(Trip)
        .options(selectinload(Trip.items))
        .where(Trip.user_id == user_id)
    )
    if active_only:
        q = q.where(Trip.status.in_(["planning", "packing", "active"]))
    q = q.order_by(Trip.created_at.desc())
    res = await session.execute(q)
    return list(res.scalars().all())


async def update_trip_status(
    session: AsyncSession, trip_id: int, status: str,
) -> Trip | None:
    trip = await get_trip(session, trip_id)
    if not trip:
        return None
    trip.status = status
    await session.commit()
    return trip


async def delete_trip(session: AsyncSession, trip_id: int) -> bool:
    trip = await get_trip(session, trip_id)
    if not trip:
        return False
    await session.delete(trip)
    await session.commit()
    return True


async def add_checklist_item(
    session: AsyncSession,
    trip_id: int,
    text: str,
    category: str = "other",
    sort_order: int = 99,
) -> ChecklistItem:
    item = ChecklistItem(
        trip_id=trip_id,
        text=text,
        category=category,
        sort_order=sort_order,
    )
    session.add(item)
    await session.commit()
    return item


async def add_template_items(
    session: AsyncSession,
    trip_id: int,
    template_items: list[tuple[str, str, int]],
) -> int:
    for text, category, sort_order in template_items:
        session.add(ChecklistItem(
            trip_id=trip_id,
            text=text,
            category=category,
            sort_order=sort_order,
        ))
    await session.commit()
    return len(template_items)


async def toggle_item(session: AsyncSession, item_id: int) -> ChecklistItem | None:
    res = await session.execute(
        select(ChecklistItem).where(ChecklistItem.id == item_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        return None
    item.checked = not item.checked
    await session.commit()
    return item


async def delete_item(session: AsyncSession, item_id: int) -> bool:
    res = await session.execute(
        select(ChecklistItem).where(ChecklistItem.id == item_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        return False
    await session.delete(item)
    await session.commit()
    return True


async def check_all(session: AsyncSession, trip_id: int) -> int:
    trip = await get_trip(session, trip_id)
    if not trip:
        return 0
    count = 0
    for item in trip.items:
        if not item.checked:
            item.checked = True
            count += 1
    if count:
        await session.commit()
    return count


async def uncheck_all(session: AsyncSession, trip_id: int) -> int:
    trip = await get_trip(session, trip_id)
    if not trip:
        return 0
    count = 0
    for item in trip.items:
        if item.checked:
            item.checked = False
            count += 1
    if count:
        await session.commit()
    return count
