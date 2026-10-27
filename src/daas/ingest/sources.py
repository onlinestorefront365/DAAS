"""State filing connectors. Add a state = add a class here and register it in SOURCES.

Both launch sources are official open-data publications:
  NY  Department of State, "Active Corporations: Beginning 1800" (data.ny.gov n9v6-gdp6)
  CO  Secretary of State, "Business Entities in Colorado" (data.colorado.gov 4ykn-tg5h, public domain)
"""

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx

from daas import enrichment as en
from daas.config import get_settings
from daas.ingest.base import BusinessRecord
from daas.ingest.socrata import SocrataClient

_LAW_OFFICE = re.compile(r"\b(ESQ|ESQUIRE|LAW|ATTORNEYS?|LLP|P ?C)\b")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _same_street(a: str | None, b: str | None) -> bool:
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())  # noqa: E731
    return bool(a and b) and norm(a) == norm(b)


def _build(
    *,
    source: str,
    registered_state: str,
    record_id: str,
    name: str,
    entity_type: str | None,
    is_foreign: bool,
    home_jurisdiction: str | None,
    status: str | None,
    formed_on: date,
    address: dict[str, str | None] | None,
    address_kind: str | None,
    county: str | None,
    contact_name: str | None,
    agent_name: str | None,
    commercial_agent: bool,
    raw: dict[str, Any],
) -> BusinessRecord:
    category, professional = en.categorize_entity(entity_type)
    industry = en.classify_industry(name)
    holding = en.is_holding_vehicle(name, industry)
    address = address or {}
    has_address = bool(address.get("street1") and (address.get("postal_code") or address.get("city")))
    return BusinessRecord(
        source=source,
        source_record_id=record_id,
        registered_state=registered_state,
        name=name,
        name_normalized=en.normalize_name(name),
        entity_type_raw=entity_type,
        entity_category=category,
        is_professional=professional,
        is_foreign=is_foreign,
        home_jurisdiction=home_jurisdiction,
        status=status,
        formed_on=formed_on,
        street1=address.get("street1") if has_address else None,
        street2=address.get("street2") if has_address else None,
        city=address.get("city") if has_address else None,
        region=address.get("region") if has_address else None,
        postal_code=address.get("postal_code") if has_address else None,
        country=address.get("country") if has_address else None,
        county=county,
        address_kind=address_kind if has_address else None,
        contact_name=contact_name,
        registered_agent_name=agent_name,
        uses_commercial_agent=commercial_agent,
        industry=industry,
        is_holding_vehicle=holding,
        lead_score=en.lead_score(
            has_business_address=has_address,
            has_contact=bool(contact_name),
            holding=holding,
            industry=industry,
            is_foreign=is_foreign,
            category=category,
            status=status,
        ),
        raw=raw,
    )


def _address(row: dict[str, Any], prefix: str, *, zip_key: str = "zip", country_key: str | None = None) -> dict:
    country = en.clean(row.get(country_key)) if country_key else "US"
    return {
        "street1": en.clean(row.get(f"{prefix}address_1") or row.get(f"{prefix}address1")),
        "street2": en.clean(row.get(f"{prefix}address_2") or row.get(f"{prefix}address2")),
        "city": en.normalize_city(row.get(f"{prefix}city")),
        "region": en.normalize_state(row.get(f"{prefix}state")),
        "postal_code": en.normalize_postal(row.get(f"{prefix}{zip_key}")),
        "country": (country or "US")[:2].upper(),
    }


class SocrataSource:
    code: str
    registered_state: str
    domain: str
    dataset_id: str
    date_field: str

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.client = SocrataClient(
            self.domain,
            self.dataset_id,
            self.date_field,
            app_token=s.socrata_app_token,
            page_size=s.ingest_page_size,
            timeout=s.http_timeout_seconds,
            transport=transport,
        )

    def fetch(self, since: date) -> Iterator[dict[str, Any]]:
        return self.client.fetch_since(since)


class NewYorkDOS(SocrataSource):
    code = "ny_dos"
    registered_state = "NY"
    domain = "data.ny.gov"
    dataset_id = "n9v6-gdp6"
    date_field = "initial_dos_filing_date"

    def map(self, row: dict[str, Any]) -> BusinessRecord | None:
        record_id = en.clean(row.get("dos_id"))
        name = en.clean(row.get("current_entity_name"))
        formed = _parse_date(row.get("initial_dos_filing_date"))
        if not (record_id and name and formed):
            return None
        entity_type = en.clean(row.get("entity_type"))
        upper_type = (entity_type or "").upper()
        is_foreign = "FOREIGN" in upper_type

        process_name = en.clean(row.get("dos_process_name"))
        agent_name = en.clean(row.get("registered_agent_name"))
        commercial = en.is_commercial_agent(agent_name) or en.is_commercial_agent(process_name)

        # Best business address: explicit location > process address that isn't an agent/lawyer.
        address, kind = None, None
        if en.clean(row.get("location_address_1")):
            address, kind = _address(row, "location_"), "location"
        elif (
            en.clean(row.get("dos_process_address_1"))
            and not en.is_commercial_agent(process_name)
            and not _LAW_OFFICE.search((process_name or "").upper().replace(".", ""))
            and not _same_street(row.get("dos_process_address_1"), row.get("registered_agent_address_1"))
        ):
            address, kind = _address(row, "dos_process_"), "process"

        jurisdiction = en.clean(row.get("jurisdiction"))
        return _build(
            source=self.code,
            registered_state=self.registered_state,
            record_id=record_id,
            name=name,
            entity_type=entity_type,
            is_foreign=is_foreign,
            home_jurisdiction=en.normalize_state(jurisdiction) or jurisdiction,
            status="Active",  # dataset only contains active entities
            formed_on=formed,
            address=address,
            address_kind=kind,
            county=en.normalize_city(row.get("county")),
            contact_name=en.person_name(row.get("chairman_name")) or en.person_name(process_name),
            agent_name=agent_name or (process_name if en.is_commercial_agent(process_name) else None),
            commercial_agent=commercial,
            raw=row,
        )


class ColoradoSOS(SocrataSource):
    code = "co_sos"
    registered_state = "CO"
    domain = "data.colorado.gov"
    dataset_id = "4ykn-tg5h"
    date_field = "entityformdate"

    def map(self, row: dict[str, Any]) -> BusinessRecord | None:
        record_id = en.clean(row.get("entityid"))
        name = en.clean(row.get("entityname"))
        formed = _parse_date(row.get("entityformdate"))
        if not (record_id and name and formed):
            return None
        entity_type = en.clean(row.get("entitytype"))

        agent_org = en.clean(row.get("agentorganizationname"))
        agent_person = " ".join(
            p for p in (en.clean(row.get("agentfirstname")), en.clean(row.get("agentlastname"))) if p
        ) or None
        agent_name = agent_org or agent_person
        commercial = en.is_commercial_agent(agent_org)

        address, kind = None, None
        for prefix, label in (("principal", "principal"), ("mailing", "mailing")):
            if en.clean(row.get(f"{prefix}address1")) and not (
                commercial and _same_street(row.get(f"{prefix}address1"), row.get("agentprincipaladdress1"))
            ):
                address = _address(row, prefix, zip_key="zipcode", country_key=f"{prefix}country")
                kind = label
                break

        jurisdiction = en.clean(row.get("jurisdictonofformation"))  # sic: upstream typo
        return _build(
            source=self.code,
            registered_state=self.registered_state,
            record_id=record_id,
            name=name,
            entity_type=entity_type,
            is_foreign=(entity_type or "").upper().startswith("F"),
            home_jurisdiction=en.normalize_state(jurisdiction) or jurisdiction,
            status=en.clean(row.get("entitystatus")),
            formed_on=formed,
            address=address,
            address_kind=kind,
            county=None,
            # An individual registered agent on a new filing is almost always the founder.
            contact_name=None if agent_org else en.person_name(agent_person),
            agent_name=agent_name,
            commercial_agent=commercial,
            raw=row,
        )


SOURCES: dict[str, type[SocrataSource]] = {cls.code: cls for cls in (NewYorkDOS, ColoradoSOS)}
