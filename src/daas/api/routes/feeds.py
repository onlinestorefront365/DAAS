import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from daas.api.deps import AuthContext, require_api_key
from daas.api.schemas import FeedIn, FeedOut, FeedPatch
from daas.config import get_settings
from daas.db import session_scope
from daas.models import Business, Feed
from daas.security import UnsafeWebhookURL, check_webhook_url, generate_webhook_secret

router = APIRouter(prefix="/v1/feeds", tags=["feeds"])


def _out(feed: Feed) -> FeedOut:
    return FeedOut(
        id=feed.id,
        name=feed.name,
        filters=feed.filters,
        webhook_url=feed.webhook_url,
        secret=feed.secret,
        active=feed.active,
        consecutive_failures=feed.consecutive_failures,
        created_at=feed.created_at,
        last_delivered_at=feed.last_delivered_at,
    )


def _validate_url(url: str) -> None:
    try:
        check_webhook_url(url, allow_private=get_settings().allow_private_webhooks)
    except UnsafeWebhookURL as exc:
        raise HTTPException(422, str(exc)) from exc


def _get_owned(session: Session, ctx: AuthContext, feed_id: uuid.UUID) -> Feed:
    feed = session.get(Feed, feed_id)
    if feed is None or feed.customer_id != ctx.customer.id:
        raise HTTPException(404, "Feed not found")
    return feed


@router.post("", response_model=FeedOut, status_code=status.HTTP_201_CREATED)
def create_feed(
    body: FeedIn,
    ctx: AuthContext = Depends(require_api_key),
    session: Session = Depends(session_scope),
) -> FeedOut:
    """Push new matching businesses to your webhook as they are ingested.

    Deliveries start from filings ingested after the feed is created and count toward the quota.
    """
    existing = session.scalar(select(func.count()).select_from(Feed).where(Feed.customer_id == ctx.customer.id))
    if existing >= ctx.plan.max_feeds:
        raise HTTPException(403, f"The {ctx.plan.name} plan allows {ctx.plan.max_feeds} feed(s).")
    url = str(body.webhook_url)
    _validate_url(url)
    feed = Feed(
        customer_id=ctx.customer.id,
        name=body.name,
        filters=body.filters.model_dump(mode="json", exclude_none=True),
        webhook_url=url,
        secret=generate_webhook_secret(),
        cursor_seq=session.scalar(select(func.coalesce(func.max(Business.seq), 0))),
    )
    session.add(feed)
    session.flush()
    session.refresh(feed)
    return _out(feed)


@router.get("", response_model=list[FeedOut])
def list_feeds(ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)):
    feeds = session.scalars(select(Feed).where(Feed.customer_id == ctx.customer.id).order_by(Feed.created_at))
    return [_out(f) for f in feeds]


@router.get("/{feed_id}", response_model=FeedOut)
def get_feed(
    feed_id: uuid.UUID, ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)
) -> FeedOut:
    return _out(_get_owned(session, ctx, feed_id))


@router.patch("/{feed_id}", response_model=FeedOut)
def update_feed(
    feed_id: uuid.UUID,
    body: FeedPatch,
    ctx: AuthContext = Depends(require_api_key),
    session: Session = Depends(session_scope),
) -> FeedOut:
    feed = _get_owned(session, ctx, feed_id)
    if body.name is not None:
        feed.name = body.name
    if body.filters is not None:
        feed.filters = body.filters.model_dump(mode="json", exclude_none=True)
    if body.webhook_url is not None:
        _validate_url(str(body.webhook_url))
        feed.webhook_url = str(body.webhook_url)
    if body.active is not None:
        feed.active = body.active
        if body.active:
            feed.consecutive_failures = 0
    return _out(feed)


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed(
    feed_id: uuid.UUID, ctx: AuthContext = Depends(require_api_key), session: Session = Depends(session_scope)
) -> None:
    session.delete(_get_owned(session, ctx, feed_id))
