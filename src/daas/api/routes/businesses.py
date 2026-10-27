import csv
import io
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from daas.api.deps import AuthContext, record_usage, require_api_key, require_quota
from daas.api.query import apply_cursor, base_query, encode_cursor, filters_from_query
from daas.api.schemas import BusinessFilters, BusinessOut, BusinessPage
from daas.db import session_scope
from daas.models import Business

router = APIRouter(prefix="/v1/businesses", tags=["businesses"])

MAX_PAGE = 100
MAX_EXPORT = 10_000


@router.get("", response_model=BusinessPage)
def search_businesses(
    response: Response,
    filters: BusinessFilters = Depends(filters_from_query),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    cursor: str | None = None,
    ctx: AuthContext = Depends(require_api_key),
    session: Session = Depends(session_scope),
) -> BusinessPage:
    """Newly registered businesses, newest first. Each returned record counts toward the monthly quota."""
    remaining = require_quota(session, ctx)
    take = min(limit, remaining)
    stmt = apply_cursor(base_query(filters, ctx.plan), cursor).limit(take + 1)
    rows = list(session.scalars(stmt))
    has_more = len(rows) > take
    rows = rows[:take]
    record_usage(ctx.customer.id, len(rows))
    remaining -= len(rows)
    response.headers["X-Quota-Remaining"] = str(remaining)
    return BusinessPage(
        data=[BusinessOut.from_model(b) for b in rows],
        next_cursor=encode_cursor(rows[-1]) if has_more and rows else None,
        quota_remaining=remaining,
    )


_CSV_COLUMNS = [
    "id", "name", "entity_type", "entity_category", "is_foreign", "home_jurisdiction", "registered_state",
    "status", "formed_on", "street1", "street2", "city", "region", "postal_code", "country", "county",
    "contact_name", "registered_agent_name", "registered_agent_is_commercial", "industry",
    "is_holding_vehicle", "lead_score", "source", "source_record_id",
]


def _csv_row(b: Business) -> list:
    return [
        b.id, b.name, b.entity_type_raw, b.entity_category, b.is_foreign, b.home_jurisdiction,
        b.registered_state, b.status, b.formed_on, b.street1, b.street2, b.city, b.region, b.postal_code,
        b.country, b.county, b.contact_name, b.registered_agent_name, b.uses_commercial_agent, b.industry,
        b.is_holding_vehicle, b.lead_score, b.source, b.source_record_id,
    ]


@router.get("/export.csv", response_class=StreamingResponse)
def export_csv(
    filters: BusinessFilters = Depends(filters_from_query),
    limit: int = Query(1000, ge=1, le=MAX_EXPORT),
    ctx: AuthContext = Depends(require_api_key),
    session: Session = Depends(session_scope),
) -> StreamingResponse:
    """Bulk CSV for CRM imports (Growth and Scale plans)."""
    if not ctx.plan.csv_export:
        raise HTTPException(403, f"CSV export is not included in the {ctx.plan.name} plan.")
    take = min(limit, require_quota(session, ctx))
    rows = list(session.scalars(apply_cursor(base_query(filters, ctx.plan), None).limit(take)))
    record_usage(ctx.customer.id, len(rows))

    def stream() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_CSV_COLUMNS)
        for b in rows:
            writer.writerow(_csv_row(b))
            if buf.tell() > 64_000:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="businesses.csv"'},
    )


@router.get("/{business_id}", response_model=BusinessOut)
def get_business(
    business_id: uuid.UUID,
    ctx: AuthContext = Depends(require_api_key),
    session: Session = Depends(session_scope),
) -> BusinessOut:
    require_quota(session, ctx)
    b = session.get(Business, business_id)
    if b is None or b.suppressed_at is not None:
        raise HTTPException(404, "Business not found")
    record_usage(ctx.customer.id, 1)
    return BusinessOut.from_model(b)
