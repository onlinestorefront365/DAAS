import hashlib
import hmac
import json
import time
from datetime import date, timedelta

from sqlalchemy import select

from conftest import auth, make_record
from daas.api.deps import record_usage
from daas.models import Business, Customer


def test_health_and_coverage(client, seed):
    seed([make_record(i) for i in range(3)])
    assert client.get("/health").json() == {"ok": True}
    cov = client.get("/v1/coverage").json()
    assert cov["total_records"] == 3
    assert "construction_trades" in cov["industries"]


def test_auth_required(client):
    assert client.get("/v1/businesses").status_code == 401
    assert client.get("/v1/businesses", headers=auth("dk_live_nope")).status_code == 401


def test_signup_then_use_key(client):
    r = client.post("/v1/signup", json={"email": "Founder@Example.com", "company": "Acme"})
    assert r.status_code == 201
    key = r.json()["api_key"]
    assert key.startswith("dk_live_")
    assert client.post("/v1/signup", json={"email": "founder@example.com"}).status_code == 409
    acct = client.get("/v1/account", headers={"X-API-Key": key}).json()
    assert acct["plan"]["code"] == "free" and acct["records_remaining"] == 100


def test_search_filters_and_pagination(client, seed, make_customer):
    _, key = make_customer("growth")
    seed(
        [make_record(i) for i in range(30)]
        + [
            make_record(100, registered_state="CO", industry="technology", name="Byte Forge LLC",
                        name_normalized="byte forge", lead_score=60, contact_name=None),
            make_record(101, is_holding_vehicle=True, name="12 Elm Holdings LLC", name_normalized="12 elm holdings"),
        ]
    )
    h = auth(key)

    r = client.get("/v1/businesses", params={"limit": 10}, headers=h)
    assert r.status_code == 200
    page = r.json()
    assert len(page["data"]) == 10 and page["next_cursor"]
    seen = {b["id"] for b in page["data"]}
    formed = [b["formed_on"] for b in page["data"]]
    assert formed == sorted(formed, reverse=True)

    total = len(seen)
    cursor = page["next_cursor"]
    while cursor:
        page = client.get("/v1/businesses", params={"limit": 10, "cursor": cursor}, headers=h).json()
        ids = {b["id"] for b in page["data"]}
        assert not ids & seen
        seen |= ids
        total += len(ids)
        cursor = page["next_cursor"]
    assert total == 32

    co = client.get("/v1/businesses", params={"state": "co"}, headers=h).json()["data"]
    assert [b["name"] for b in co] == ["Byte Forge LLC"]
    assert co[0]["registered_agent"] == {"name": None, "is_commercial": False}

    multi = client.get("/v1/businesses", params={"industry": "technology,construction_trades", "limit": 100}, headers=h)
    assert len(multi.json()["data"]) == 32

    assert len(client.get("/v1/businesses", params={"min_score": 80, "limit": 100}, headers=h).json()["data"]) == 31
    assert len(client.get("/v1/businesses", params={"has_contact": "false"}, headers=h).json()["data"]) == 1
    assert len(client.get("/v1/businesses", params={"exclude_holding": "true", "limit": 100}, headers=h).json()["data"]) == 31
    fuzzy = client.get("/v1/businesses", params={"q": "byte forj"}, headers=h).json()["data"]
    assert [b["name"] for b in fuzzy] == ["Byte Forge LLC"]
    assert client.get("/v1/businesses", params={"q": "100%_"}, headers=h).json()["data"] == []

    assert client.get("/v1/businesses", params={"industry": "bogus"}, headers=h).status_code == 422
    assert client.get("/v1/businesses", params={"cursor": "!!"}, headers=h).status_code == 400


def test_history_window_by_plan(client, seed, make_customer):
    _, free_key = make_customer("free")
    _, growth_key = make_customer("growth")
    seed([make_record(1, formed_on=date.today() - timedelta(days=400))])
    assert client.get("/v1/businesses", headers=auth(free_key)).json()["data"] == []
    assert len(client.get("/v1/businesses", headers=auth(growth_key)).json()["data"]) == 1


def test_quota_metering_and_exhaustion(client, seed, make_customer, session):
    customer, key = make_customer("free")
    seed([make_record(i) for i in range(10)])
    record_usage(customer.id, 95)

    r = client.get("/v1/businesses", params={"limit": 50}, headers=auth(key))
    assert len(r.json()["data"]) == 5  # clamped to remaining quota
    assert r.headers["X-Quota-Remaining"] == "0"

    r = client.get("/v1/businesses", headers=auth(key))
    assert r.status_code == 402
    assert client.get("/v1/account", headers=auth(key)).json()["records_used"] == 100


def test_rate_limit(client, make_customer):
    _, key = make_customer("free")  # 10 rpm
    codes = [client.get("/v1/account", headers=auth(key)).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_get_business_and_suppression(client, seed, make_customer, session):
    _, key = make_customer("growth")
    seed([make_record(1)])
    biz = session.scalar(select(Business))
    r = client.get(f"/v1/businesses/{biz.id}", headers=auth(key))
    assert r.status_code == 200 and r.json()["contact_name"] == "Jane Doe"

    admin = {"X-Admin-Token": "test-admin"}
    assert client.post(f"/admin/businesses/{biz.id}/suppress", headers=admin).status_code == 200
    assert client.get(f"/v1/businesses/{biz.id}", headers=auth(key)).status_code == 404
    assert client.get("/v1/businesses", headers=auth(key)).json()["data"] == []


def test_csv_export_is_plan_gated(client, seed, make_customer):
    _, starter = make_customer("starter")
    _, growth = make_customer("growth")
    seed([make_record(i) for i in range(3)])
    assert client.get("/v1/businesses/export.csv", headers=auth(starter)).status_code == 403
    r = client.get("/v1/businesses/export.csv", headers=auth(growth))
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,name,") and len(lines) == 4


def test_key_management(client, make_customer):
    _, key = make_customer("starter")
    new = client.post("/v1/account/keys", json={"name": "ci"}, headers=auth(key)).json()
    assert client.get("/v1/account", headers=auth(new["api_key"])).status_code == 200
    assert len(client.get("/v1/account/keys", headers=auth(key)).json()) == 2
    assert client.delete(f"/v1/account/keys/{new['id']}", headers=auth(key)).status_code == 204
    assert client.get("/v1/account", headers=auth(new["api_key"])).status_code == 401


def test_feed_crud_and_plan_limit(client, make_customer):
    _, free = make_customer("free")
    _, starter = make_customer("starter")
    body = {"name": "NY trades", "filters": {"state": ["NY"], "industry": ["construction_trades"]},
            "webhook_url": "http://hooks.test/in"}
    assert client.post("/v1/feeds", json=body, headers=auth(free)).status_code == 403

    r = client.post("/v1/feeds", json=body, headers=auth(starter))
    assert r.status_code == 201
    feed = r.json()
    assert feed["secret"].startswith("whsec_") and feed["filters"]["state"] == ["NY"]
    assert client.post("/v1/feeds", json=body, headers=auth(starter)).status_code == 403  # max 1

    patched = client.patch(f"/v1/feeds/{feed['id']}", json={"active": False}, headers=auth(starter)).json()
    assert patched["active"] is False
    assert client.delete(f"/v1/feeds/{feed['id']}", headers=auth(starter)).status_code == 204
    assert client.get("/v1/feeds", headers=auth(starter)).json() == []


def test_feed_rejects_private_webhook(client, make_customer, monkeypatch):
    from daas.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_private_webhooks", False)
    _, key = make_customer("growth")
    for url in ("http://example.com/hook", "https://127.0.0.1/hook"):
        r = client.post("/v1/feeds", json={"name": "x", "webhook_url": url}, headers=auth(key))
        assert r.status_code == 422, url


def test_admin(client, make_customer):
    assert client.get("/admin/customers").status_code == 401
    admin = {"X-Admin-Token": "test-admin"}
    r = client.post("/admin/customers", json={"email": "buyer@corp.com", "plan": "scale"}, headers=admin)
    assert r.status_code == 201
    acct = client.get("/v1/account", headers=auth(r.json()["api_key"])).json()
    assert acct["plan"]["code"] == "scale"
    cid = r.json()["customer_id"]
    assert client.patch(f"/admin/customers/{cid}", json={"status": "disabled"}, headers=admin).status_code == 200
    assert client.get("/v1/account", headers=auth(r.json()["api_key"])).status_code == 403
    assert any(c["email"] == "buyer@corp.com" for c in client.get("/admin/customers", headers=admin).json())


def _stripe_post(client, event: dict, secret: str = "whsec_test"):
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": f"t={ts},v1={sig}"})


def test_stripe_webhook_lifecycle(client, make_customer, session):
    customer, _ = make_customer("free")
    assert _stripe_post(client, {"type": "x"}, secret="wrong").status_code == 400

    _stripe_post(client, {"type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": str(customer.id), "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"plan": "starter"}}}})
    session.refresh(customer)
    assert (customer.plan, customer.stripe_customer_id) == ("starter", "cus_1")

    _stripe_post(client, {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "past_due",
        "items": {"data": [{"price": {"id": "price_growth"}}]}}}})
    session.refresh(customer)
    assert (customer.plan, customer.status) == ("growth", "past_due")

    _stripe_post(client, {"type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "canceled"}}})
    session.refresh(customer)
    assert (customer.plan, customer.status, customer.stripe_subscription_id) == ("free", "active", None)


def test_checkout_requires_stripe_config(client, make_customer):
    _, key = make_customer("free")
    assert client.post("/v1/billing/checkout", json={"plan": "growth"}, headers=auth(key)).status_code == 503


def test_plans_listing(client):
    codes = [p["code"] for p in client.get("/v1/plans").json()]
    assert codes == ["free", "starter", "growth", "scale"]
    assert Customer  # imported for fixtures
