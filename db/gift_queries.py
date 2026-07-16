"""Database queries for gift module."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import GiftIdea, Person


# ---- Persons ----

async def count_persons(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(Person.id)).where(Person.user_id == user_id)
    )
    return res.scalar() or 0


async def add_person(
    session: AsyncSession,
    user_id: int,
    name: str,
    birthday: date | None = None,
    rel_type: str | None = None,
) -> Person:
    person = Person(
        user_id=user_id,
        name=name,
        birthday=birthday,
        rel_type=rel_type,
    )
    session.add(person)
    await session.commit()
    return person


async def get_person(session: AsyncSession, person_id: int) -> Person | None:
    res = await session.execute(
        select(Person)
        .options(selectinload(Person.gifts))
        .where(Person.id == person_id)
    )
    return res.scalar_one_or_none()


async def list_persons(session: AsyncSession, user_id: int) -> list[Person]:
    res = await session.execute(
        select(Person)
        .options(selectinload(Person.gifts))
        .where(Person.user_id == user_id)
        .order_by(Person.name)
    )
    return list(res.scalars().all())


async def delete_person(session: AsyncSession, person_id: int) -> bool:
    person = await get_person(session, person_id)
    if not person:
        return False
    await session.delete(person)
    await session.commit()
    return True


# ---- Gift Ideas ----

async def add_gift(
    session: AsyncSession,
    user_id: int,
    person_id: int,
    title: str,
    price_estimate: float | None = None,
    event: str | None = None,
) -> GiftIdea:
    gift = GiftIdea(
        user_id=user_id,
        person_id=person_id,
        title=title,
        price_estimate=price_estimate,
        event=event,
    )
    session.add(gift)
    await session.commit()
    return gift


async def get_gift(session: AsyncSession, gift_id: int) -> GiftIdea | None:
    res = await session.execute(
        select(GiftIdea)
        .options(selectinload(GiftIdea.person))
        .where(GiftIdea.id == gift_id)
    )
    return res.scalar_one_or_none()


async def list_gifts_for_person(
    session: AsyncSession, person_id: int,
) -> list[GiftIdea]:
    res = await session.execute(
        select(GiftIdea)
        .where(GiftIdea.person_id == person_id)
        .order_by(GiftIdea.created_at.desc())
    )
    return list(res.scalars().all())


async def list_all_ideas(session: AsyncSession, user_id: int) -> list[GiftIdea]:
    res = await session.execute(
        select(GiftIdea)
        .options(selectinload(GiftIdea.person))
        .where(GiftIdea.user_id == user_id, GiftIdea.status == "idea")
        .order_by(GiftIdea.created_at.desc())
    )
    return list(res.scalars().all())


async def update_gift_status(
    session: AsyncSession, gift_id: int, status: str, given_date: date | None = None,
) -> GiftIdea | None:
    gift = await get_gift(session, gift_id)
    if not gift:
        return None
    gift.status = status
    if given_date:
        gift.given_date = given_date
    await session.commit()
    return gift


async def delete_gift(session: AsyncSession, gift_id: int) -> bool:
    gift = await get_gift(session, gift_id)
    if not gift:
        return False
    await session.delete(gift)
    await session.commit()
    return True
