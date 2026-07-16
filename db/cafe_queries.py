"""Database queries for cafe module."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import CafePlace, CafeVisit


async def count_cafes(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(CafePlace.id)).where(CafePlace.user_id == user_id)
    )
    return res.scalar() or 0


async def add_cafe(
    session: AsyncSession,
    user_id: int,
    name: str,
    address: str | None = None,
    cuisine: str | None = None,
    is_wishlist: bool = False,
) -> CafePlace:
    cafe = CafePlace(
        user_id=user_id,
        name=name,
        address=address,
        cuisine=cuisine,
        is_wishlist=is_wishlist,
    )
    session.add(cafe)
    await session.commit()
    return cafe


async def get_cafe(session: AsyncSession, cafe_id: int) -> CafePlace | None:
    res = await session.execute(
        select(CafePlace)
        .options(selectinload(CafePlace.visits))
        .where(CafePlace.id == cafe_id)
    )
    return res.scalar_one_or_none()


async def list_cafes(
    session: AsyncSession, user_id: int, wishlist_only: bool = False,
) -> list[CafePlace]:
    q = (
        select(CafePlace)
        .options(selectinload(CafePlace.visits))
        .where(CafePlace.user_id == user_id)
    )
    if wishlist_only:
        q = q.where(CafePlace.is_wishlist.is_(True))
    q = q.order_by(CafePlace.name)
    res = await session.execute(q)
    return list(res.scalars().all())


async def delete_cafe(session: AsyncSession, cafe_id: int) -> bool:
    cafe = await get_cafe(session, cafe_id)
    if not cafe:
        return False
    await session.delete(cafe)
    await session.commit()
    return True


async def toggle_wishlist(session: AsyncSession, cafe_id: int) -> CafePlace | None:
    res = await session.execute(
        select(CafePlace).where(CafePlace.id == cafe_id)
    )
    cafe = res.scalar_one_or_none()
    if not cafe:
        return None
    cafe.is_wishlist = not cafe.is_wishlist
    await session.commit()
    return cafe


async def add_visit(
    session: AsyncSession,
    cafe_id: int,
    user_id: int,
    visit_date: date,
    rating: int | None = None,
    spent: float | None = None,
    dish: str | None = None,
    notes: str | None = None,
) -> CafeVisit:
    visit = CafeVisit(
        cafe_id=cafe_id,
        user_id=user_id,
        visit_date=visit_date,
        rating=rating,
        spent=spent,
        dish=dish,
        notes=notes,
    )
    session.add(visit)
    cafe_res = await session.execute(
        select(CafePlace).where(CafePlace.id == cafe_id)
    )
    cafe = cafe_res.scalar_one_or_none()
    if cafe and cafe.is_wishlist:
        cafe.is_wishlist = False
    await session.commit()
    return visit


async def list_visits(
    session: AsyncSession, user_id: int, limit: int = 20, offset: int = 0,
) -> list[CafeVisit]:
    res = await session.execute(
        select(CafeVisit)
        .options(selectinload(CafeVisit.cafe))
        .where(CafeVisit.user_id == user_id)
        .order_by(CafeVisit.visit_date.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(res.scalars().all())


async def cafe_stats(
    session: AsyncSession, cafe_id: int,
) -> tuple[int, float | None, float | None]:
    visits_res = await session.execute(
        select(CafeVisit).where(CafeVisit.cafe_id == cafe_id)
    )
    visits = list(visits_res.scalars().all())
    count = len(visits)
    ratings = [v.rating for v in visits if v.rating is not None]
    spends = [v.spent for v in visits if v.spent is not None]
    avg_rating = sum(ratings) / len(ratings) if ratings else None
    avg_spent = sum(spends) / len(spends) if spends else None
    return count, avg_rating, avg_spent


async def top_cafes(
    session: AsyncSession, user_id: int, limit: int = 10,
) -> list[tuple[CafePlace, int, float | None, float | None]]:
    cafes = await list_cafes(session, user_id)
    results = []
    for cafe in cafes:
        if cafe.is_wishlist:
            continue
        visits = cafe.visits or []
        count = len(visits)
        if count == 0:
            continue
        ratings = [v.rating for v in visits if v.rating is not None]
        spends = [v.spent for v in visits if v.spent is not None]
        avg_r = sum(ratings) / len(ratings) if ratings else None
        avg_s = sum(spends) / len(spends) if spends else None
        results.append((cafe, count, avg_r, avg_s))
    results.sort(key=lambda x: (-(x[2] or 0), -x[1]))
    return results[:limit]
