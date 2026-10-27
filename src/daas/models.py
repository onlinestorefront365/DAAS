import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Business(Base):
    """One registered entity from a state filing source. The core asset."""

    __tablename__ = "businesses"
    __table_args__ = (
        UniqueConstraint("source", "source_record_id", name="uq_business_source_record"),
        Index("ix_business_formed", "formed_on", "id"),
        Index("ix_business_state_formed", "registered_state", "formed_on"),
        Index("ix_business_industry", "industry"),
        Index("ix_business_postal", "postal_code"),
        Index(
            "ix_business_name_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Monotonic insertion order; feeds use it as a delivery cursor.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)

    source: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(64))
    registered_state: Mapped[str] = mapped_column(String(2))  # state where filed

    name: Mapped[str] = mapped_column(Text)
    name_normalized: Mapped[str] = mapped_column(Text)
    entity_type_raw: Mapped[str | None] = mapped_column(Text)
    entity_category: Mapped[str] = mapped_column(String(32))  # llc|corporation|nonprofit|partnership|other
    is_professional: Mapped[bool] = mapped_column(Boolean, default=False)
    is_foreign: Mapped[bool] = mapped_column(Boolean, default=False)  # out-of-state company expanding in
    home_jurisdiction: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64))
    formed_on: Mapped[date] = mapped_column(Date)

    street1: Mapped[str | None] = mapped_column(Text)
    street2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str | None] = mapped_column(String(2))
    county: Mapped[str | None] = mapped_column(Text)
    address_kind: Mapped[str | None] = mapped_column(String(24))  # principal|location|process|mailing

    contact_name: Mapped[str | None] = mapped_column(Text)
    registered_agent_name: Mapped[str | None] = mapped_column(Text)
    uses_commercial_agent: Mapped[bool] = mapped_column(Boolean, default=False)

    industry: Mapped[str | None] = mapped_column(String(48))
    is_holding_vehicle: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_score: Mapped[int] = mapped_column(SmallInteger, default=0)

    raw: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set when a business owner asks to be removed. Suppressed rows are never served.
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceState(Base):
    __tablename__ = "source_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    watermark: Mapped[date | None] = mapped_column(Date)  # max formed_on ingested
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|failed
    since: Mapped[date | None] = mapped_column(Date)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    company: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(String(16), default="free")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|past_due|canceled|disabled
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="customer")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="default")
    prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="api_keys")


class UsageCounter(Base):
    """Monthly metering per customer. `records` is what quotas and invoices key off."""

    __tablename__ = "usage_counters"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    requests: Mapped[int] = mapped_column(BigInteger, default=0)
    records: Mapped[int] = mapped_column(BigInteger, default=0)


class RateLimitWindow(Base):
    __tablename__ = "rate_limit_windows"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Feed(Base):
    """A saved search whose new matches are pushed to the customer's webhook."""

    __tablename__ = "feeds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    webhook_url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(64))
    cursor_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedDelivery(Base):
    __tablename__ = "feed_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    feed_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    record_count: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
