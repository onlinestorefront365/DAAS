"""Stripe Checkout for upgrades, Billing Portal for self-service, webhooks to sync plan state."""

import json
import logging
import uuid

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from daas.api.deps import AuthContext, require_api_key
from daas.api.schemas import CheckoutIn, UrlOut
from daas.config import Settings, get_settings
from daas.db import session_scope
from daas.models import Customer

log = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])


def _price_to_plan(s: Settings) -> dict[str, str]:
    return {
        price: plan
        for plan, price in (
            ("starter", s.stripe_price_starter),
            ("growth", s.stripe_price_growth),
            ("scale", s.stripe_price_scale),
        )
        if price
    }


def _require_stripe() -> Settings:
    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(503, "Billing is not configured.")
    return s


@router.post("/v1/billing/checkout", response_model=UrlOut)
def create_checkout(body: CheckoutIn, ctx: AuthContext = Depends(require_api_key)) -> UrlOut:
    s = _require_stripe()
    price = {v: k for k, v in _price_to_plan(s).items()}.get(body.plan)
    if not price:
        raise HTTPException(503, f"No Stripe price configured for plan {body.plan}.")
    c = ctx.customer
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price, "quantity": 1}],
        "client_reference_id": str(c.id),
        "success_url": f"{s.public_base_url}/billing/success",
        "cancel_url": f"{s.public_base_url}/billing/cancel",
        "metadata": {"customer_id": str(c.id), "plan": body.plan},
        "subscription_data": {"metadata": {"customer_id": str(c.id)}},
    }
    if c.stripe_customer_id:
        params["customer"] = c.stripe_customer_id
    else:
        params["customer_email"] = c.email
    session = stripe.checkout.Session.create(api_key=s.stripe_secret_key, **params)
    return UrlOut(url=session.url)


@router.post("/v1/billing/portal", response_model=UrlOut)
def create_portal(ctx: AuthContext = Depends(require_api_key)) -> UrlOut:
    s = _require_stripe()
    if not ctx.customer.stripe_customer_id:
        raise HTTPException(409, "No billing account yet. Start with POST /v1/billing/checkout.")
    portal = stripe.billing_portal.Session.create(
        api_key=s.stripe_secret_key,
        customer=ctx.customer.stripe_customer_id,
        return_url=s.public_base_url,
    )
    return UrlOut(url=portal.url)


_ACTIVE = {"active", "trialing"}
_PAST_DUE = {"past_due", "unpaid", "incomplete"}


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    session: Session = Depends(session_scope),
) -> dict:
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise HTTPException(503, "Billing is not configured.")
    payload = await request.body()
    try:
        stripe.WebhookSignature.verify_header(payload.decode(), stripe_signature, s.stripe_webhook_secret, 300)
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(400, "Invalid signature") from exc
    event = json.loads(payload)
    apply_event(session, event, _price_to_plan(s))
    return {"received": True}


def apply_event(session: Session, event: dict, price_to_plan: dict[str, str]) -> None:
    kind = event.get("type")
    obj = event.get("data", {}).get("object", {})

    if kind == "checkout.session.completed":
        try:
            customer = session.get(Customer, uuid.UUID(obj.get("client_reference_id") or ""))
        except ValueError:
            customer = None
        if customer is None:
            log.warning("checkout without known client_reference_id: %s", obj.get("id"))
            return
        customer.stripe_customer_id = obj.get("customer")
        customer.stripe_subscription_id = obj.get("subscription")
        plan = (obj.get("metadata") or {}).get("plan")
        if plan in set(price_to_plan.values()):
            customer.plan = plan
        customer.status = "active"
        return

    if kind in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        customer = session.scalar(select(Customer).where(Customer.stripe_customer_id == obj.get("customer")))
        if customer is None:
            log.warning("subscription event for unknown stripe customer %s", obj.get("customer"))
            return
        sub_status = obj.get("status")
        if kind == "customer.subscription.deleted" or sub_status in {"canceled", "incomplete_expired"}:
            customer.plan = "free"
            customer.status = "active"
            customer.stripe_subscription_id = None
            return
        items = (obj.get("items") or {}).get("data") or []
        price_id = items[0].get("price", {}).get("id") if items else None
        if price_id in price_to_plan:
            customer.plan = price_to_plan[price_id]
        customer.stripe_subscription_id = obj.get("id")
        if sub_status in _ACTIVE:
            customer.status = "active"
        elif sub_status in _PAST_DUE:
            # Keep serving during Stripe's dunning retries; cancellation downgrades.
            customer.status = "past_due"
