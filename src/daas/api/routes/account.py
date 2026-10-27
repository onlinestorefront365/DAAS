import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from daas.api.deps import AuthContext, current_period, records_used, require_api_key
from daas.api.schemas import AccountOut, KeyIn, KeyOut, NewKeyOut, PlanOut, SignupIn
from daas.config import get_settings
from daas.db import session_scope
from daas.models import ApiKey, Customer
from daas.plans import PLANS, Plan
from daas.security import generate_api_key

router = APIRouter(tags=["account"])

MAX_KEYS = 5


def plan_out(plan: Plan) -> PlanOut:
    return PlanOut(**plan.__dict__)


def issue_key(session: Session, customer: Customer, name: str = "default") -> NewKeyOut:
    plaintext, prefix, digest = generate_api_key()
    key = ApiKey(customer_id=customer.id, name=name, prefix=prefix, key_hash=digest)
    session.add(key)
    session.flush()
    return NewKeyOut(id=key.id, api_key=plaintext, prefix=prefix)


@router.get("/v1/plans", response_model=list[PlanOut])
def list_plans() -> list[PlanOut]:
    return [plan_out(p) for p in PLANS.values()]


@router.post("/v1/signup", response_model=NewKeyOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, session: Session = Depends(session_scope)) -> NewKeyOut:
    """Self-serve free plan. Returns an API key once; upgrade with POST /v1/billing/checkout."""
    if not get_settings().signup_enabled:
        raise HTTPException(403, "Self-serve signup is closed. Contact sales.")
    email = body.email.lower()
    if session.scalar(select(Customer).where(func.lower(Customer.email) == email)):
        raise HTTPException(409, "An account with this email already exists.")
    customer = Customer(email=email, company=body.company, plan="free")
    session.add(customer)
    session.flush()
    return issue_key(session, customer)


@router.get("/v1/account", response_model=AccountOut)
def account(ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)) -> AccountOut:
    used = records_used(session, ctx.customer.id)
    c = ctx.customer
    return AccountOut(
        id=c.id,
        email=c.email,
        company=c.company,
        status=c.status,
        plan=plan_out(ctx.plan),
        period=current_period(),
        records_used=used,
        records_remaining=max(0, ctx.plan.monthly_records - used),
    )


@router.get("/v1/account/keys", response_model=list[KeyOut])
def list_keys(ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)):
    keys = session.scalars(select(ApiKey).where(ApiKey.customer_id == ctx.customer.id).order_by(ApiKey.created_at))
    return [KeyOut.model_validate(k, from_attributes=True) for k in keys]


@router.post("/v1/account/keys", response_model=NewKeyOut, status_code=status.HTTP_201_CREATED)
def create_key(
    body: KeyIn, ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)
) -> NewKeyOut:
    active = session.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.customer_id == ctx.customer.id, ApiKey.revoked_at.is_(None))
    )
    if active >= MAX_KEYS:
        raise HTTPException(403, f"At most {MAX_KEYS} active keys per account.")
    return issue_key(session, ctx.customer, body.name)


@router.delete("/v1/account/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(
    key_id: uuid.UUID, ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)
) -> None:
    key = session.get(ApiKey, key_id)
    if key is None or key.customer_id != ctx.customer.id:
        raise HTTPException(404, "Key not found")
    key.revoked_at = key.revoked_at or datetime.now(timezone.utc)
