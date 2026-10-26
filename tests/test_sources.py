from datetime import date

import httpx

from conftest import load_fixture
from daas.ingest.socrata import SocrataClient
from daas.ingest.sources import ColoradoSOS, NewYorkDOS


def test_ny_mapping():
    rows = load_fixture("ny_rows.json")
    src = NewYorkDOS()
    founder, agent_filed, foreign = (src.map(r) for r in rows)

    assert founder.source_record_id == "8055110"
    assert founder.formed_on == date(2026, 10, 24)
    assert founder.contact_name == "Harmanvir Singh"
    assert founder.city == "Hicksville" and founder.postal_code == "11801"
    assert founder.address_kind == "process"
    assert not founder.uses_commercial_agent

    # Placeholder process name -> the process address is the company's own.
    assert agent_filed.contact_name is None
    assert agent_filed.street1 == "8714 Atlantic Ave # 1"
    assert agent_filed.uses_commercial_agent
    assert agent_filed.registered_agent_name == "LEGALZOOM USCA, INC."

    # Commercial agent as process recipient -> no business address.
    assert foreign.is_foreign and foreign.home_jurisdiction == "DE"
    assert foreign.street1 is None
    assert foreign.is_professional and foreign.industry == "healthcare"
    assert foreign.lead_score < founder.lead_score


def test_co_mapping():
    rows = load_fixture("co_rows.json")
    src = ColoradoSOS()
    fund, tattoo, roofing = (src.map(r) for r in rows)

    assert fund.is_foreign and fund.home_jurisdiction == "CA"
    assert fund.is_holding_vehicle
    assert fund.uses_commercial_agent and fund.contact_name is None

    assert tattoo.contact_name == "Armon Laleh"
    assert tattoo.industry == "beauty_personal_care"
    assert tattoo.city == "Denver" and tattoo.address_kind == "principal"

    # Principal address equals the commercial agent's office -> not a lead address.
    assert roofing.street1 is None
    assert roofing.industry == "construction_trades"


def test_map_rejects_incomplete_rows():
    assert NewYorkDOS().map({"dos_id": "1"}) is None
    assert ColoradoSOS().map({"entityid": "1", "entityname": "X", "entityformdate": "garbage"}) is None


def test_socrata_paginates_and_retries(monkeypatch):
    monkeypatch.setattr("daas.ingest.socrata.time.sleep", lambda _: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if len(calls) == 1:
            return httpx.Response(503)
        offset = int(request.url.params["$offset"])
        return httpx.Response(200, json=[{"n": offset + i} for i in range(2 if offset == 0 else 1)])

    client = SocrataClient("example.org", "abcd-1234", "d", page_size=2, transport=httpx.MockTransport(handler))
    rows = list(client.fetch_since(date(2026, 1, 1)))
    assert [r["n"] for r in rows] == [0, 1, 2]
    assert calls[1]["$where"] == "d >= '2026-01-01T00:00:00'"
    assert calls[-1]["$offset"] == "2"
