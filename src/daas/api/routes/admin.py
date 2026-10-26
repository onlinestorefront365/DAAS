import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from daas.api.deps import current_period, require_admin
from daas.api.routes.account import issue_key
from daas.api.schemas import AdminCustomerIn, AdminCustomerPatch, NewKeyOut
from daas.db import session_scope
from daas.models import Business, Customer, IngestRun, UsageCounter

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)], include_in_schema=False)


@router.get("/customers")
def list_customers(session: Session = Depends(session_scope)) -> list[dict]:
    period = current_period()
    rows = session.execute(
        select(Customer, UsageCounter.records, UsageCounter.requests)
        .outerjoin(UsageCounter, (UsageCounter.customer_id == Customer.id) & (UsageCounter.period == period))
        .order_by(Customer.created_at.desc())
    ).all()
    return [
        {
            "id": str(c.id),
            "email": c.email,
            "company": c.company,
            "plan": c.plan,
            "status": c.status,
            "stripe_customer_id": c.stripe_customer_id,
            "period": period,
            "records": records or 0,
            "requests": requests or 0,
            "created_at": c.created_at.isoformat(),
        }
        for c, records, requests in rows
    ]


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def create_customer(body: AdminCustomerIn, session: Session = Depends(session_scope)) -> dict:
    """Sales-led onboarding: create an account on any plan and hand over its first key."""
    email = body.email.lower()
    if session.scalar(select(Customer).where(func.lower(Customer.email) == email)):
        raise HTTPException(409, "Customer exists")
    customer = Customer(email=email, company=body.company, plan=body.plan)
    session.add(customer)
    session.flush()
    key = issue_key(session, customer)
    return {"customer_id": str(customer.id), "api_key": key.api_key}


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: uuid.UUID, body: AdminCustomerPatch, session: Session = Depends(session_scope)):
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    if body.plan:
        customer.plan = body.plan
    if body.status:
        customer.status = body.status
    return {"id": str(customer.id), "plan": customer.plan, "status": customer.status}


@router.post("/customers/{customer_id}/keys", response_model=NewKeyOut, status_code=status.HTTP_201_CREATED)
def create_customer_key(customer_id: uuid.UUID, session: Session = Depends(session_scope)) -> NewKeyOut:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return issue_key(session, customer, "admin-issued")


@router.post("/businesses/{business_id}/suppress")
def suppress_business(business_id: uuid.UUID, session: Session = Depends(session_scope)) -> dict:
    """Honor a removal request. The row stays (so re-ingestion can't resurrect it) but is never served."""
    b = session.get(Business, business_id)
    if b is None:
        raise HTTPException(404, "Business not found")
    b.suppressed_at = b.suppressed_at or datetime.now(timezone.utc)
    return {"id": str(b.id), "suppressed_at": b.suppressed_at.isoformat()}


@router.get("/ingest-runs")
def ingest_runs(limit: int = Query(20, le=200), session: Session = Depends(session_scope)) -> list[dict]:
    runs = session.scalars(select(IngestRun).order_by(IngestRun.id.desc()).limit(limit))
    return [
        {
            "id": r.id,
            "source": r.source,
            "status": r.status,
            "since": r.since.isoformat() if r.since else None,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "fetched": r.fetched,
            "inserted": r.inserted,
            "updated": r.updated,
            "skipped": r.skipped,
            "error": r.error,
        }
        for r in runs
    ]
