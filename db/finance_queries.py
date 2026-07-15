"""Запросы для финансового модуля."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import FinCategory, FinTransaction, MerchantRule


def _month_range(month: str) -> tuple[date, date]:
    year, m = int(month[:4]), int(month[5:7])
    start = date(year, m, 1)
    end = date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)
    return start, end


# ---------- Категории ----------

async def count_categories(session: AsyncSession, user_id: int) -> int:
    res = await session.scalar(
        select(func.count())
        .select_from(FinCategory)
        .where(FinCategory.user_id == user_id)
    )
    return res or 0


async def get_categories(
    session: AsyncSession, user_id: int, cat_type: str
) -> list[FinCategory]:
    res = await session.execute(
        select(FinCategory)
        .where(FinCategory.user_id == user_id, FinCategory.cat_type == cat_type)
        .order_by(FinCategory.sort_order)
    )
    return list(res.scalars().all())


async def get_category(session: AsyncSession, cat_id: int) -> FinCategory | None:
    res = await session.execute(
        select(FinCategory).where(FinCategory.id == cat_id)
    )
    return res.scalar_one_or_none()


# ---------- Мерчант-правила ----------

async def match_merchant(
    session: AsyncSession, user_id: int, merchant_text: str
) -> FinCategory | None:
    text_lower = merchant_text.lower()
    res = await session.execute(
        select(MerchantRule)
        .where(MerchantRule.user_id == user_id)
        .order_by(MerchantRule.match_count.desc())
    )
    for rule in res.scalars().all():
        if rule.pattern in text_lower:
            rule.match_count += 1
            await session.commit()
            return await get_category(session, rule.category_id)
    return None


async def learn_merchant(
    session: AsyncSession, user_id: int, merchant_text: str, category_id: int
) -> None:
    pattern = merchant_text.lower().strip()
    if not pattern:
        return

    res = await session.execute(
        select(MerchantRule).where(
            MerchantRule.user_id == user_id,
            MerchantRule.pattern == pattern,
        )
    )
    rule = res.scalar_one_or_none()

    if rule:
        rule.category_id = category_id
        rule.match_count += 1
    else:
        session.add(MerchantRule(
            user_id=user_id,
            pattern=pattern,
            category_id=category_id,
            match_count=1,
        ))
    await session.commit()


# ---------- Транзакции ----------

async def add_transaction(session: AsyncSession, **fields) -> FinTransaction:
    tx = FinTransaction(**fields)
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return tx


async def delete_transaction(session: AsyncSession, tx_id: int) -> bool:
    res = await session.execute(
        select(FinTransaction).where(FinTransaction.id == tx_id)
    )
    tx = res.scalar_one_or_none()
    if tx is None:
        return False
    await session.delete(tx)
    await session.commit()
    return True


async def list_transactions(
    session: AsyncSession,
    user_id: int,
    *,
    month: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[FinTransaction]:
    stmt = (
        select(FinTransaction)
        .options(joinedload(FinTransaction.category))
        .where(FinTransaction.user_id == user_id)
    )
    if month:
        start, end = _month_range(month)
        stmt = stmt.where(
            FinTransaction.tx_date >= start, FinTransaction.tx_date < end
        )
    stmt = stmt.order_by(
        FinTransaction.tx_date.desc(), FinTransaction.created_at.desc()
    )
    res = await session.execute(stmt.offset(offset).limit(limit))
    return list(res.scalars().all())


# ---------- Агрегации ----------

async def monthly_totals(
    session: AsyncSession, user_id: int, month: str
) -> tuple[float, float]:
    start, end = _month_range(month)

    income = await session.scalar(
        select(func.coalesce(func.sum(FinTransaction.amount), 0.0)).where(
            FinTransaction.user_id == user_id,
            FinTransaction.tx_type == "income",
            FinTransaction.tx_date >= start,
            FinTransaction.tx_date < end,
        )
    ) or 0.0

    expenses = await session.scalar(
        select(func.coalesce(func.sum(FinTransaction.amount), 0.0)).where(
            FinTransaction.user_id == user_id,
            FinTransaction.tx_type == "expense",
            FinTransaction.tx_date >= start,
            FinTransaction.tx_date < end,
        )
    ) or 0.0

    return float(income), float(expenses)


async def category_totals(
    session: AsyncSession,
    user_id: int,
    month: str,
    tx_type: str = "expense",
) -> list[tuple[str, str, float]]:
    start, end = _month_range(month)
    res = await session.execute(
        select(
            FinCategory.icon,
            FinCategory.name,
            func.sum(FinTransaction.amount),
        )
        .join(FinCategory, FinTransaction.category_id == FinCategory.id)
        .where(
            FinTransaction.user_id == user_id,
            FinTransaction.tx_type == tx_type,
            FinTransaction.tx_date >= start,
            FinTransaction.tx_date < end,
        )
        .group_by(FinCategory.id)
        .order_by(func.sum(FinTransaction.amount).desc())
    )
    return [(r[0], r[1], float(r[2])) for r in res.all()]
