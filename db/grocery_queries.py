"""Database queries for grocery module."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import GroceryItem


async def count_items(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(GroceryItem.id)).where(GroceryItem.user_id == user_id)
    )
    return res.scalar() or 0


async def list_all_items(
    session: AsyncSession, user_id: int, active_only: bool = True
) -> list[GroceryItem]:
    q = select(GroceryItem).where(GroceryItem.user_id == user_id)
    if active_only:
        q = q.where(GroceryItem.active.is_(True))
    q = q.order_by(GroceryItem.sort_order, GroceryItem.name)
    res = await session.execute(q)
    return list(res.scalars().all())


async def list_due_items(
    session: AsyncSession, user_id: int, ref_date: date | None = None,
) -> list[GroceryItem]:
    if ref_date is None:
        ref_date = date.today()
    items = await list_all_items(session, user_id)
    due = []
    for item in items:
        if item.last_bought is None:
            due.append(item)
        else:
            days_since = (ref_date - item.last_bought).days
            if days_since >= item.buy_freq_days:
                due.append(item)
    return due


def group_by_store(items: list[GroceryItem]) -> dict[str, list[GroceryItem]]:
    groups: dict[str, list[GroceryItem]] = {}
    for item in items:
        store = item.usual_store or "пятёрочка"
        groups.setdefault(store, []).append(item)
    return groups


async def mark_bought_by_store(
    session: AsyncSession, user_id: int, store: str, bought_date: date | None = None,
) -> int:
    if bought_date is None:
        bought_date = date.today()
    due = await list_due_items(session, user_id, bought_date)
    count = 0
    for item in due:
        s = item.usual_store or "пятёрочка"
        if s == store:
            item.last_bought = bought_date
            count += 1
    if count:
        await session.commit()
    return count


async def mark_bought_all(
    session: AsyncSession, user_id: int, bought_date: date | None = None,
) -> int:
    if bought_date is None:
        bought_date = date.today()
    due = await list_due_items(session, user_id, bought_date)
    for item in due:
        item.last_bought = bought_date
    if due:
        await session.commit()
    return len(due)


async def mark_bought_item(
    session: AsyncSession, item_id: int, bought_date: date | None = None,
) -> None:
    if bought_date is None:
        bought_date = date.today()
    await session.execute(
        update(GroceryItem)
        .where(GroceryItem.id == item_id)
        .values(last_bought=bought_date)
    )
    await session.commit()


async def add_item(
    session: AsyncSession,
    user_id: int,
    name: str,
    store: str,
    freq_days: int,
    category: str = "vegetable",
    icon: str = "🛒",
) -> GroceryItem:
    item = GroceryItem(
        user_id=user_id,
        name=name,
        category=category,
        icon=icon,
        usual_store=store,
        buy_freq_days=freq_days,
    )
    session.add(item)
    await session.commit()
    return item


async def toggle_item(session: AsyncSession, item_id: int) -> bool:
    res = await session.execute(
        select(GroceryItem).where(GroceryItem.id == item_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        return False
    item.active = not item.active
    await session.commit()
    return True


async def delete_item(session: AsyncSession, item_id: int) -> bool:
    res = await session.execute(
        select(GroceryItem).where(GroceryItem.id == item_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        return False
    await session.delete(item)
    await session.commit()
    return True
