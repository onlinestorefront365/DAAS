import hashlib
import hmac
import json

import httpx

from conftest import make_record
from daas.api.deps import record_usage, records_used
from daas.feeds import MAX_CONSECUTIVE_FAILURES, deliver_all
from daas.models import Feed, FeedDelivery


def _feed(session, customer, cursor=0, **filters):
    feed = Feed(customer_id=customer.id, name="f", filters=filters, webhook_url="http://hooks.test/in",
                secret="whsec_abc", cursor_seq=cursor)
    session.add(feed)
    session.commit()
    return feed


def _recorder(status=200):
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(status)

    return received, httpx.Client(transport=httpx.MockTransport(handler))


def test_delivers_matching_new_records_once(session, seed, make_customer):
    customer, _ = make_customer("starter")
    seed([make_record(i) for i in range(3)])
    feed = _feed(session, customer, cursor=1, state=["NY"])  # created after record 1
    seed([make_record(10, registered_state="CO")])

    received, client = _recorder()
    stats = deliver_all(session, client)
    assert stats.records == 2 and len(received) == 1

    req = received[0]
    payload = json.loads(req.content)
    assert payload["count"] == 2 and {r["source"]["record_id"] for r in payload["data"]} == {"1", "2"}
    ts, sig = (part.split("=", 1)[1] for part in req.headers["X-DaaS-Signature"].split(","))
    expected = hmac.new(b"whsec_abc", f"{ts}.".encode() + req.content, hashlib.sha256).hexdigest()
    assert sig == expected
    assert records_used(session, customer.id) == 2

    session.refresh(feed)
    assert feed.cursor_seq == 4  # advanced past the non-matching CO row too
    assert deliver_all(session, client).records == 0


def test_failures_hold_cursor_and_eventually_disable(session, seed, make_customer):
    customer, _ = make_customer("starter")
    feed = _feed(session, customer)
    seed([make_record(1)])
    _, client = _recorder(status=500)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        deliver_all(session, client)
    session.refresh(feed)
    assert feed.cursor_seq == 0 and not feed.active
    assert session.query(FeedDelivery).filter_by(success=False).count() == MAX_CONSECUTIVE_FAILURES
    assert records_used(session, customer.id) == 0


def test_respects_quota(session, seed, make_customer):
    customer, _ = make_customer("starter")
    record_usage(customer.id, 4_998)
    _feed(session, customer)
    seed([make_record(i) for i in range(5)])
    received, client = _recorder()
    assert deliver_all(session, client).records == 2
    assert len(json.loads(received[0].content)["data"]) == 2


def test_downgraded_customer_gets_nothing(session, seed, make_customer):
    customer, _ = make_customer("free")
    _feed(session, customer)
    seed([make_record(1)])
    received, client = _recorder()
    deliver_all(session, client)
    assert received == []
