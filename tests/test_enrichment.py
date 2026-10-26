import pytest

from daas import enrichment as en


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ROADWISE SERVICES INC.", "roadwise services"),
        ("Laleh Tattoo, L.L.C.", "laleh tattoo"),
        ("Smith & Sons Co.", "smith & sons"),
    ],
)
def test_normalize_name(raw, expected):
    assert en.normalize_name(raw) == expected


def test_normalize_state_and_postal():
    assert en.normalize_state("NEW YORK") == "NY"
    assert en.normalize_state("co") == "CO"
    assert en.normalize_state("Ontario") is None
    assert en.normalize_postal("11801-1234") == "11801"
    assert en.normalize_postal("123") is None


@pytest.mark.parametrize(
    "name",
    ["NORTHWEST REGISTERED AGENT LLC", "LegalZoom USCA, Inc.", "C T CORPORATION SYSTEM", "Inc Authority RA"],
)
def test_commercial_agents(name):
    assert en.is_commercial_agent(name)


def test_individual_is_not_commercial_agent():
    assert not en.is_commercial_agent("HARMANVIR SINGH")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HARMANVIR SINGH", "Harmanvir Singh"),
        ("c/o Jane Q Public", "Jane Q Public"),
        ("THE LIMITED LIABILITY COMPANY", None),
        ("ROON LLC", None),
        ("JOHN SMITH, ESQ.", None),
        ("Steel Equities", None),
        ("The Farm Soho", None),
        ("Madonna", None),
    ],
)
def test_person_name(raw, expected):
    assert en.person_name(raw) == expected


def test_categorize_entity():
    assert en.categorize_entity("DOMESTIC LIMITED LIABILITY COMPANY") == ("llc", False)
    assert en.categorize_entity("DOMESTIC PROFESSIONAL SERVICE CORPORATION") == ("corporation", True)
    assert en.categorize_entity("DOMESTIC NOT-FOR-PROFIT CORPORATION") == ("nonprofit", False)
    assert en.categorize_entity("DPC") == ("corporation", False)
    assert en.categorize_entity("FLLC") == ("llc", False)
    assert en.categorize_entity("DLP") == ("partnership", False)


def test_industry():
    assert en.classify_industry("Laleh Tattoo LLC") == "beauty_personal_care"
    assert en.classify_industry("Summit Roofing Co") == "construction_trades"
    assert en.classify_industry("BLUE HARBOR DENTAL PLLC") == "healthcare"
    assert en.classify_industry("Marketing Mavens LLC") == "marketing_media"
    assert en.classify_industry("ROON LLC") is None


def test_holding_vehicle():
    assert en.is_holding_vehicle("NEW HAT LOFTS HOLDINGS LLC")
    assert en.is_holding_vehicle("43 BROOKWOOD DRIVE, LLC")
    assert en.is_holding_vehicle("483 FIRST NECK LLC")
    assert not en.is_holding_vehicle("24 Hour Fitness LLC", industry="fitness")
    assert not en.is_holding_vehicle("Laleh Tattoo LLC")


def test_lead_score_bounds_and_order():
    strong = en.lead_score(
        has_business_address=True, has_contact=True, holding=False, industry="x",
        is_foreign=True, category="llc", status="Good Standing",
    )
    weak = en.lead_score(
        has_business_address=False, has_contact=False, holding=True, industry=None,
        is_foreign=False, category="nonprofit", status="Delinquent",
    )
    assert strong == 90
    assert weak == 0
