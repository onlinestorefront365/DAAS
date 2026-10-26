import base64
import json
import uuid
from datetime import date, timedelta

from fastapi import HTTPException, Query
from sqlalchemy import Select, func, select, tuple_

from daas.api.schemas import BusinessFilters
from daas.enrichment import normalize_name
from daas.models import Business
from daas.plans import Plan


def _split(values: list[str] | None) -> list[str] | None:
    """Accept both ?state=NY&state=CO and ?state=NY,CO."""
    if not values:
        return None
    out = [v.strip() for raw in values for v in raw.split(",") if v.strip()]
    return out or None


def filters_from_query(
    state: list[str] | None = Query(None),
    formed_after: date | None = None,
    formed_before: date | None = None,
    entity_category: list[str] | None = Query(None),
    industry: list[str] | None = Query(None),
    region: list[str] | None = Query(None),
    city: str | None = None,
    postal_code: list[str] | None = Query(None),
    county: str | None = None,
    q: str | None = None,
    min_score: int | None = None,
    has_contact: bool | None = None,
    has_address: bool | None = None,
    is_foreign: bool | None = None,
    exclude_holding: bool = False,
) -> BusinessFilters:
    try:
        return BusinessFilters(
            state=_split(state),
            formed_after=formed_after,
            formed_before=formed_before,
            entity_category=_split(entity_category),
            industry=_split(industry),
            region=_split(region),
            city=city,
            postal_code=_split(postal_code),
            county=county,
            q=q,
            min_score=min_score,
            has_contact=has_contact,
            has_address=has_address,
            is_foreign=is_foreign,
            exclude_holding=exclude_holding,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def base_query(filters: BusinessFilters, plan: Plan | None) -> Select:
    stmt = select(Business).where(Business.suppressed_at.is_(None))
    f = filters
    formed_after = f.formed_after
    if plan and plan.history_days is not None:
        floor = date.today() - timedelta(days=plan.history_days)
        formed_after = max(formed_after, floor) if formed_after else floor
    if formed_after:
        stmt = stmt.where(Business.formed_on >= formed_after)
    if f.formed_before:
        stmt = stmt.where(Business.formed_on <= f.formed_before)
    if f.state:
        stmt = stmt.where(Business.registered_state.in_(f.state))
    if f.entity_category:
        stmt = stmt.where(Business.entity_category.in_(f.entity_category))
    if f.industry:
        stmt = stmt.where(Business.industry.in_(f.industry))
    if f.region:
        stmt = stmt.where(Business.region.in_(f.region))
    if f.city:
        stmt = stmt.where(func.lower(Business.city) == f.city.strip().lower())
    if f.postal_code:
        stmt = stmt.where(Business.postal_code.in_(f.postal_code))
    if f.county:
        stmt = stmt.where(func.lower(Business.county) == f.county.strip().lower())
    if f.q:
        term = normalize_name(f.q)
        if term:
            # Trigram index serves both: substring for exact fragments, similarity for typos.
            stmt = stmt.where(
                Business.name_normalized.ilike(f"%{_escape_like(term)}%")
                | Business.name_normalized.op("%")(term)
            )
    if f.min_score is not None:
        stmt = stmt.where(Business.lead_score >= f.min_score)
    if f.has_contact is not None:
        stmt = stmt.where(Business.contact_name.isnot(None) if f.has_contact else Business.contact_name.is_(None))
    if f.has_address is not None:
        stmt = stmt.where(Business.street1.isnot(None) if f.has_address else Business.street1.is_(None))
    if f.is_foreign is not None:
        stmt = stmt.where(Business.is_foreign.is_(f.is_foreign))
    if f.exclude_holding:
        stmt = stmt.where(Business.is_holding_vehicle.is_(False))
    return stmt


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_cursor(b: Business) -> str:
    raw = json.dumps([b.formed_on.isoformat(), str(b.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def apply_cursor(stmt: Select, cursor: str | None) -> Select:
    """Newest filings first; keyset pagination on (formed_on, id)."""
    if cursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            formed, ident = json.loads(base64.urlsafe_b64decode(padded))
            key = (date.fromisoformat(formed), uuid.UUID(ident))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Invalid cursor") from exc
        stmt = stmt.where(tuple_(Business.formed_on, Business.id) < key)
    return stmt.order_by(Business.formed_on.desc(), Business.id.desc())
