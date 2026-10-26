"""Webhook delivery for saved feeds. Run after each ingest (the scheduler does this)."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from daas.api.deps import record_usage, records_used
from daas.api.query import base_query
from daas.api.schemas import BusinessFilters, BusinessOut
from daas.config import get_settings
from daas.models import Business, Customer, Feed, FeedDelivery
from daas.plans import get_plan
from daas.security import UnsafeWebhookURL, check_webhook_url, sign_payload

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 10


@dataclass
class DeliveryStats:
    feeds: int = 0
    batches: int = 0
    records: int = 0
    failures: int = 0


def deliver_all(session: Session, client: httpx.Client | None = None) -> DeliveryStats:
    s = get_settings()
    stats = DeliveryStats()
    owns_client = client is None
    client = client or httpx.Client(timeout=s.webhook_timeout_seconds, follow_redirects=False)
    try:
        feed_ids = session.scalars(select(Feed.id).where(Feed.active.is_(True)).order_by(Feed.created_at)).all()
        for feed_id in feed_ids:
            stats.feeds += 1
            deliver_feed(session, session.get(Feed, feed_id), client, stats)
    finally:
        if owns_client:
            client.close()
    return stats


def deliver_feed(session: Session, feed: Feed, client: httpx.Client, stats: DeliveryStats) -> None:
    s = get_settings()
    customer = session.get(Customer, feed.customer_id)
    plan = get_plan(customer.plan)
    if customer.status == "disabled" or plan.max_feeds == 0:
        return
    filters = BusinessFilters(**feed.filters)
    head = session.scalar(select(func.coalesce(func.max(Business.seq), 0)))

    while True:
        remaining = plan.monthly_records - records_used(session, customer.id)
        if remaining <= 0:
            log.info("feed %s paused: quota exhausted", feed.id)
            return
        take = min(s.feed_batch_size, remaining)
        rows = list(
            session.scalars(
                base_query(filters, plan)
                .where(Business.seq > feed.cursor_seq, Business.seq <= head)
                .order_by(Business.seq)
                .limit(take)
            )
        )
        if not rows:
            # Nothing matched up to head: skip past non-matching rows so they aren't re-scanned.
            feed.cursor_seq = max(feed.cursor_seq, head)
            session.commit()
            return

        body = json.dumps(
            {
                "feed_id": str(feed.id),
                "count": len(rows),
                "data": [BusinessOut.from_model(b).model_dump(mode="json") for b in rows],
            }
        ).encode()
        ok, code, error = _post(client, feed, body, s.allow_private_webhooks)
        session.add(FeedDelivery(feed_id=feed.id, record_count=len(rows), status_code=code, success=ok, error=error))
        stats.batches += 1
        if not ok:
            stats.failures += 1
            feed.consecutive_failures += 1
            if feed.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                feed.active = False
                log.warning("feed %s disabled after %s failures", feed.id, feed.consecutive_failures)
            session.commit()
            return

        record_usage(customer.id, len(rows))
        stats.records += len(rows)
        feed.consecutive_failures = 0
        feed.last_delivered_at = datetime.now(timezone.utc)
        feed.cursor_seq = head if len(rows) < take else rows[-1].seq
        session.commit()
        if len(rows) < take:
            return


def _post(client: httpx.Client, feed: Feed, body: bytes, allow_private: bool) -> tuple[bool, int | None, str | None]:
    try:
        # Re-resolve at send time: DNS may have changed since the feed was created.
        check_webhook_url(feed.webhook_url, allow_private=allow_private)
        ts = int(time.time())
        resp = client.post(
            feed.webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-DaaS-Signature": sign_payload(feed.secret, ts, body),
                "User-Agent": "daas-feeds/1.0",
            },
        )
        ok = 200 <= resp.status_code < 300
        return ok, resp.status_code, None if ok else resp.text[:500]
    except (httpx.HTTPError, UnsafeWebhookURL) as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:500]
