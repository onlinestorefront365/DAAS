import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from daas.config import get_settings
from daas.db import get_engine, session_scope
from daas.models import ApiKey, Customer, RateLimitWindow, UsageCounter
from daas.plans import Plan, get_plan
from daas.security import hash_api_key


@dataclass
class AuthContext:
    customer: Customer
    api_key: ApiKey
    plan: Plan


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(
    response: Response,
    session: Session = Depends(session_scope),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> AuthContext:
    plaintext = _extract_key(authorization, x_api_key)
    if not plaintext:
        raise HTTPException(401, "Missing API key. Send `Authorization: Bearer <key>`.")
    key = session.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(plaintext), ApiKey.revoked_at.is_(None))
    )
    if key is None:
        raise HTTPException(401, "Invalid or revoked API key.")
    customer = key.customer
    if customer.status == "disabled":
        raise HTTPException(403, "Account disabled. Contact support.")
    plan = get_plan(customer.plan)
    _enforce_rate_limit(customer, plan, response)
    session.execute(
        update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=datetime.now(timezone.utc))
    )
    return AuthContext(customer=customer, api_key=key, plan=plan)


def _enforce_rate_limit(customer: Customer, plan: Plan, response: Response) -> None:
    """Fixed one-minute window in Postgres. Runs in its own transaction so rejected
    requests still count and the counter survives request rollbacks."""
    now = datetime.now(timezone.utc)
    window = now.replace(second=0, microsecond=0)
    stmt = (
        insert(RateLimitWindow)
        .values(customer_id=customer.id, window_start=window, count=1)
        .on_conflict_do_update(
            index_elements=[RateLimitWindow.customer_id, RateLimitWindow.window_start],
            set_={"count": RateLimitWindow.count + 1},
        )
        .returning(RateLimitWindow.count)
    )
    with get_engine().begin() as conn:
        count = conn.execute(stmt).scalar_one()
    remaining = max(0, plan.requests_per_minute - count)
    response.headers["X-RateLimit-Limit"] = str(plan.requests_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if count > plan.requests_per_minute:
        raise HTTPException(
            429,
            f"Rate limit of {plan.requests_per_minute} requests/minute exceeded.",
            headers={"Retry-After": str(60 - now.second)},
        )


def records_used(session: Session, customer_id, period: str | None = None) -> int:
    used = session.scalar(
        select(UsageCounter.records).where(
            UsageCounter.customer_id == customer_id, UsageCounter.period == (period or current_period())
        )
    )
    return used or 0


def quota_remaining(session: Session, ctx: AuthContext) -> int:
    return max(0, ctx.plan.monthly_records - records_used(session, ctx.customer.id))


def require_quota(session: Session, ctx: AuthContext) -> int:
    remaining = quota_remaining(session, ctx)
    if remaining <= 0:
        raise HTTPException(
            402,
            f"Monthly quota of {ctx.plan.monthly_records} records reached on the {ctx.plan.name} plan. "
            "Upgrade via POST /v1/billing/checkout.",
        )
    return remaining


def record_usage(customer_id, records: int, requests: int = 1) -> None:
    """Meter in a separate transaction so usage is committed even if the response fails later."""
    stmt = (
        insert(UsageCounter)
        .values(customer_id=customer_id, period=current_period(), requests=requests, records=records)
        .on_conflict_do_update(
            index_elements=[UsageCounter.customer_id, UsageCounter.period],
            set_={
                "requests": UsageCounter.requests + requests,
                "records": UsageCounter.records + records,
            },
        )
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_token
    if not expected:
        raise HTTPException(404, "Not found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "Invalid admin token")
