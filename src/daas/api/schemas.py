import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

from daas.enrichment import INDUSTRIES
from daas.models import Business

EntityCategory = Literal["llc", "corporation", "nonprofit", "partnership", "other"]


class BusinessFilters(BaseModel):
    """Shared by search, export and feeds so a saved feed matches exactly what search returns."""

    state: list[str] | None = Field(None, description="Registered state codes, e.g. NY, CO")
    formed_after: date | None = Field(None, description="Inclusive")
    formed_before: date | None = Field(None, description="Inclusive")
    entity_category: list[EntityCategory] | None = None
    industry: list[str] | None = None
    region: list[str] | None = Field(None, description="State of the business address")
    city: str | None = None
    postal_code: list[str] | None = None
    county: str | None = None
    q: str | None = Field(None, min_length=2, max_length=100, description="Fuzzy name search")
    min_score: int | None = Field(None, ge=0, le=100)
    has_contact: bool | None = None
    has_address: bool | None = None
    is_foreign: bool | None = None
    exclude_holding: bool = False

    @field_validator("state", "region", mode="after")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        return [s.strip().upper() for s in v] if v else v

    @field_validator("industry", mode="after")
    @classmethod
    def _known_industry(cls, v: list[str] | None) -> list[str] | None:
        if v:
            unknown = set(v) - set(INDUSTRIES)
            if unknown:
                raise ValueError(f"unknown industry: {sorted(unknown)}; see GET /v1/coverage")
        return v


class Address(BaseModel):
    street1: str | None
    street2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    county: str | None
    kind: str | None


class RegisteredAgent(BaseModel):
    name: str | None
    is_commercial: bool


class SourceRef(BaseModel):
    code: str
    record_id: str


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    entity_type: str | None
    entity_category: str
    is_professional: bool
    is_foreign: bool
    home_jurisdiction: str | None
    registered_state: str
    status: str | None
    formed_on: date
    address: Address
    contact_name: str | None
    registered_agent: RegisteredAgent
    industry: str | None
    is_holding_vehicle: bool
    lead_score: int
    source: SourceRef
    first_seen_at: datetime

    @classmethod
    def from_model(cls, b: Business) -> "BusinessOut":
        return cls(
            id=b.id,
            name=b.name,
            entity_type=b.entity_type_raw,
            entity_category=b.entity_category,
            is_professional=b.is_professional,
            is_foreign=b.is_foreign,
            home_jurisdiction=b.home_jurisdiction,
            registered_state=b.registered_state,
            status=b.status,
            formed_on=b.formed_on,
            address=Address(
                street1=b.street1,
                street2=b.street2,
                city=b.city,
                region=b.region,
                postal_code=b.postal_code,
                country=b.country,
                county=b.county,
                kind=b.address_kind,
            ),
            contact_name=b.contact_name,
            registered_agent=RegisteredAgent(name=b.registered_agent_name, is_commercial=b.uses_commercial_agent),
            industry=b.industry,
            is_holding_vehicle=b.is_holding_vehicle,
            lead_score=b.lead_score,
            source=SourceRef(code=b.source, record_id=b.source_record_id),
            first_seen_at=b.first_seen_at,
        )


class BusinessPage(BaseModel):
    data: list[BusinessOut]
    next_cursor: str | None
    quota_remaining: int


class FeedIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    filters: BusinessFilters = Field(default_factory=BusinessFilters)
    webhook_url: HttpUrl


class FeedPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    filters: BusinessFilters | None = None
    webhook_url: HttpUrl | None = None
    active: bool | None = None


class FeedOut(BaseModel):
    id: uuid.UUID
    name: str
    filters: dict
    webhook_url: str
    secret: str
    active: bool
    consecutive_failures: int
    created_at: datetime
    last_delivered_at: datetime | None


class SignupIn(BaseModel):
    email: EmailStr
    company: str | None = Field(None, max_length=200)


class KeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class NewKeyOut(BaseModel):
    id: uuid.UUID
    api_key: str = Field(description="Shown once. Store it securely.")
    prefix: str


class KeyIn(BaseModel):
    name: str = Field("default", min_length=1, max_length=64)


class PlanOut(BaseModel):
    code: str
    name: str
    monthly_price_usd: int
    monthly_records: int
    requests_per_minute: int
    max_feeds: int
    csv_export: bool
    history_days: int | None


class AccountOut(BaseModel):
    id: uuid.UUID
    email: str
    company: str | None
    status: str
    plan: PlanOut
    period: str
    records_used: int
    records_remaining: int


class CheckoutIn(BaseModel):
    plan: Literal["starter", "growth", "scale"]


class UrlOut(BaseModel):
    url: str


class AdminCustomerIn(BaseModel):
    email: EmailStr
    company: str | None = None
    plan: Literal["free", "starter", "growth", "scale"] = "free"


class AdminCustomerPatch(BaseModel):
    plan: Literal["free", "starter", "growth", "scale"] | None = None
    status: Literal["active", "past_due", "canceled", "disabled"] | None = None
