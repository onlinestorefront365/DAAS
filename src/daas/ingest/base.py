import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass
class BusinessRecord:
    """Normalized, enriched record ready to upsert. Field names mirror models.Business."""

    source: str
    source_record_id: str
    registered_state: str
    name: str
    name_normalized: str
    entity_type_raw: str | None
    entity_category: str
    is_professional: bool
    is_foreign: bool
    home_jurisdiction: str | None
    status: str | None
    formed_on: date
    street1: str | None
    street2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    county: str | None
    address_kind: str | None
    contact_name: str | None
    registered_agent_name: str | None
    uses_commercial_agent: bool
    industry: str | None
    is_holding_vehicle: bool
    lead_score: int
    raw: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        payload = asdict(self)
        payload["formed_on"] = self.formed_on.isoformat()
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class Source(Protocol):
    """A connector: knows how to page raw rows from upstream and map them."""

    code: str
    registered_state: str

    def fetch(self, since: date) -> Iterator[dict[str, Any]]: ...

    def map(self, row: dict[str, Any]) -> BusinessRecord | None: ...
