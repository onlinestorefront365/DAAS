from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from daas.db import session_scope
from daas.enrichment import INDUSTRIES
from daas.models import Business, SourceState

router = APIRouter(tags=["meta"])


@router.get("/health", include_in_schema=False)
def health(session: Session = Depends(session_scope)) -> dict:
    session.execute(text("select 1"))
    return {"ok": True}


@router.get("/v1/coverage")
def coverage(session: Session = Depends(session_scope)) -> dict:
    """Public: what we cover and how fresh it is. Doubles as a sales page data source."""
    rows = session.execute(
        select(
            Business.source,
            Business.registered_state,
            func.count(),
            func.min(Business.formed_on),
            func.max(Business.formed_on),
            SourceState.last_success_at,
        )
        .outerjoin(SourceState, SourceState.source == Business.source)
        .where(Business.suppressed_at.is_(None))
        .group_by(Business.source, Business.registered_state, SourceState.last_success_at)
        .order_by(Business.source)
    ).all()
    return {
        "sources": [
            {
                "source": src,
                "state": st,
                "records": count,
                "earliest_formed_on": lo,
                "latest_formed_on": hi,
                "last_refreshed_at": refreshed,
            }
            for src, st, count, lo, hi, refreshed in rows
        ],
        "total_records": sum(r[2] for r in rows),
        "industries": list(INDUSTRIES),
        "entity_categories": ["llc", "corporation", "nonprofit", "partnership", "other"],
    }
