from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text

from app.core.database_pool import db_pool


async def calculate_monthly_revenue(
    property_id: str, tenant_id: str, month: int, year: int
) -> Dict[str, Any]:
    """Sum check-in revenue within the property's local calendar month."""
    await db_pool.initialize()
    async with db_pool.get_session() as session:
        result = await session.execute(
            text("SELECT timezone FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
            {"property_id": property_id, "tenant_id": tenant_id},
        )
        property_timezone = result.scalar_one_or_none()
        if property_timezone is None:
            raise HTTPException(status_code=404, detail="Property not found")

        local_timezone = ZoneInfo(property_timezone)
        start = datetime(year, month, 1, tzinfo=local_timezone)
        end = datetime(
            year + (month == 12), 1 if month == 12 else month + 1, 1,
            tzinfo=local_timezone,
        )
        result = await session.execute(
            text("""
                SELECT currency, SUM(total_amount) AS total, COUNT(*) AS count
                FROM reservations
                WHERE property_id = :property_id AND tenant_id = :tenant_id
                  AND check_in_date >= :start AND check_in_date < :end
                GROUP BY currency
            """),
            {
                "property_id": property_id, "tenant_id": tenant_id,
                "start": start.astimezone(timezone.utc),
                "end": end.astimezone(timezone.utc),
            },
        )
        rows = result.mappings().all()
        if len(rows) > 1:
            raise HTTPException(status_code=422, detail="Cannot sum multiple currencies")
        row = rows[0] if rows else {"total": Decimal("0"), "currency": "USD", "count": 0}
        # Sum sub-cent amounts exactly, then round once for the reported total.
        total = row["total"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "property_id": property_id, "tenant_id": tenant_id,
            "total": str(total), "currency": row["currency"], "count": row["count"],
        }
