"""Normalization and derived signals. This is where raw filings become sellable leads.

Every rule here is deterministic and cheap so the whole archive can be re-scored
when rules change (`daas rescore`).
"""

import re

US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "PUERTO RICO": "PR",
}
_STATE_CODES = set(US_STATES.values())

_ENTITY_SUFFIXES = re.compile(
    r"\b(L\.?L\.?C|L\.?L\.?P|L\.?P|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|"
    r"PLLC|P\.?L\.?L\.?C|P\.?C|PC|PBC|LLLP)\b\.?",
)
_NON_ALNUM = re.compile(r"[^A-Z0-9& ]+")
_SPACES = re.compile(r"\s+")


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = _SPACES.sub(" ", str(value)).strip()
    return value or None


def normalize_name(name: str) -> str:
    """Lowercased, punctuation- and suffix-stripped name for search and dedupe."""
    upper = _NON_ALNUM.sub(" ", name.upper().replace(".", ""))
    upper = _ENTITY_SUFFIXES.sub(" ", upper)
    return _SPACES.sub(" ", upper).strip().lower()


def normalize_state(value: str | None) -> str | None:
    value = clean(value)
    if not value:
        return None
    upper = value.upper().replace(".", "")
    if upper in _STATE_CODES:
        return upper
    return US_STATES.get(upper)


def normalize_postal(value: str | None) -> str | None:
    value = clean(value)
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return digits[:5] if len(digits) >= 5 else None


def normalize_city(value: str | None) -> str | None:
    value = clean(value)
    return value.title() if value else None


# --- Registered agents ------------------------------------------------------
# Built from the most frequent agents in NY/CO filings. A commercial agent's address
# is the agent's office, not the business, so it must never be sold as a lead address.
_COMMERCIAL_AGENT_PATTERNS = re.compile(
    r"REGISTERED AGENT|AGENT SERVICE|CORPORATE SERVICE|CORPORATION SERVICE|CORPORATE CREATIONS|"
    r"C ?T CORPORATION|LEGALZOOM|ZENBUSINESS|INCORP|COGENCY|CORPORATION AGENTS|BUSINESS FILING|"
    r"LEGALINC|LEGALCORP|VCORP|RESIDENT ?AGENT|NYSCORPORATION|USACORP|PARACORP|SIMPLEBIZ|SPIEGEL|"
    r"INC AUTHORITY|CAPITOL SERVICES|CAPITOL CORPORATE|URS AGENTS|ENTITY PROTECT|\bRA\b|FILE RIGHT|"
    r"CORPORATE FILINGS|TELOS LEGAL|METRO CORPORATE|METRO BUSINESS SERVICES|MOUNTAIN BUSINESS|"
    r"STREAMWAY|NORTHWEST|HARBOR COMPLIANCE|BIZFILINGS|INCFILE|NATIONAL REGISTERED|AGENTS INC"
)
# NY lets filers put a placeholder instead of a person as the process recipient.
_PLACEHOLDER_NAMES = re.compile(
    r"^(C/?O )?(THE )?(LIMITED LIABILITY COMPANY|LLC|COMPANY|CORP|CORPORATION|ENTITY|PARTNERSHIP|"
    r"REGISTERED AGENT REVOKED)$"
)
_ORG_TOKENS = re.compile(
    r"\b(LLC|L L C|INC|CORP|CORPORATION|COMPANY|CO|LTD|LLP|LP|PC|PLLC|P C|ESQ|ESQUIRE|LAW|GROUP|"
    r"SERVICES|ASSOCIATES|PARTNERS|FIRM|TRUST|BANK|ATTORNEYS?)\b"
)


def _upper_compact(value: str) -> str:
    return _SPACES.sub(" ", re.sub(r"[.,]", "", value.upper())).strip()


def is_commercial_agent(name: str | None) -> bool:
    name = clean(name)
    return bool(name) and bool(_COMMERCIAL_AGENT_PATTERNS.search(_upper_compact(name)))


def is_placeholder_name(name: str | None) -> bool:
    name = clean(name)
    return bool(name) and bool(_PLACEHOLDER_NAMES.match(_upper_compact(name)))


def person_name(name: str | None) -> str | None:
    """Return a title-cased name if `name` looks like an individual, else None."""
    name = clean(name)
    if not name:
        return None
    upper = _upper_compact(re.sub(r"^c/o\s+", "", name, flags=re.I))
    if (
        upper.startswith("THE ")
        or is_commercial_agent(upper)
        or is_placeholder_name(upper)
        or _ORG_TOKENS.search(upper)
        or classify_industry(upper)
        or is_holding_vehicle(upper)
    ):
        return None
    words = upper.split()
    if not 2 <= len(words) <= 4 or any(ch.isdigit() for ch in upper):
        return None
    return " ".join(w.capitalize() for w in words)


# --- Entity type ------------------------------------------------------------
def categorize_entity(raw_type: str | None) -> tuple[str, bool]:
    """Map a free-text or coded entity type to (category, is_professional)."""
    t = (raw_type or "").upper()
    professional = "PROFESSIONAL" in t
    if "NOT-FOR-PROFIT" in t or "NONPROFIT" in t or t in {"DNC", "FNC"}:
        return "nonprofit", professional
    if "LIMITED LIABILITY COMPANY" in t or t in {"DLLC", "FLLC"}:
        return "llc", professional
    if "PARTNERSHIP" in t or t in {"DLP", "FLP", "DLLP", "FLLP", "DLLLP", "FLLLP", "GP", "DLPA", "FLPA"}:
        return "partnership", professional
    if "CORPORATION" in t or t.startswith(("DPC", "FPC", "DC5", "DLCA", "FLCA", "FCOOP")):
        # Colorado codes: DPC/FPC = (for-)profit corporation, DC55/56 = cooperatives.
        return "corporation", professional
    return "other", professional


# --- Industry ---------------------------------------------------------------
# Ordered: first match wins. Keyword hits on the entity name only, so precision
# beats recall; unmatched names stay null rather than guessed.
_INDUSTRY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("cannabis", ("CANNABIS", "DISPENSARY", "HEMP", "CBD", "MARIJUANA")),
    ("childcare", ("DAYCARE", "DAY CARE", "CHILDCARE", "CHILD CARE", "PRESCHOOL", "MONTESSORI")),
    ("healthcare", ("MEDICAL", "HEALTH", "CLINIC", "DENTAL", "DENTIST", "THERAPY", "THERAPEUTICS", "PHARMACY",
                    "CHIROPRACTIC", "PHYSICAL THERAPY", "PEDIATRIC", "ORTHO", "HOSPICE", "HOME CARE", "NURSING",
                    "MD", "DDS", "PSYCH", "COUNSELING", "WELLNESS", "MEDSPA", "MED SPA", "OPTOMETRY")),
    ("beauty_personal_care", ("SALON", "BEAUTY", "NAILS", "NAIL", "BARBER", "LASH", "BROW", "SPA", "COSMETIC",
                              "SKIN", "HAIR", "TATTOO", "ESTHETIC", "AESTHETIC")),
    ("fitness", ("FITNESS", "GYM", "YOGA", "PILATES", "CROSSFIT", "MARTIAL ARTS", "BOXING")),
    ("restaurant_food", ("RESTAURANT", "CAFE", "COFFEE", "PIZZA", "PIZZERIA", "BAKERY", "GRILL", "KITCHEN",
                         "DELI", "BISTRO", "TACO", "TAQUERIA", "SUSHI", "CATERING", "BBQ", "BURGER", "FOOD",
                         "FOODS", "BAR", "TAVERN", "PUB", "BREWING", "BREWERY", "WINERY", "EATERY", "DINER")),
    ("construction_trades", ("CONSTRUCTION", "CONTRACTING", "CONTRACTOR", "CONTRACTORS", "BUILDERS", "BUILDING",
                             "ROOFING", "PLUMBING", "ELECTRIC", "ELECTRICAL", "HVAC", "HEATING", "MECHANICAL",
                             "REMODELING", "RENOVATION", "RENOVATIONS", "CONCRETE", "MASONRY", "PAINTING",
                             "FLOORING", "EXCAVATION", "DRYWALL", "CARPENTRY", "GENERAL CONTRACTOR", "WELDING")),
    ("home_services", ("CLEANING", "LANDSCAPING", "LAWN", "PEST", "HANDYMAN", "JANITORIAL", "MAID", "MOVING",
                       "MOVERS", "POOL", "TREE", "SNOW", "JUNK", "GUTTER", "WINDOW", "CARPET")),
    ("transportation_logistics", ("TRUCKING", "TRANSPORT", "TRANSPORTATION", "LOGISTICS", "FREIGHT", "DELIVERY",
                                  "COURIER", "HAULING", "CARGO", "LIMO", "LIMOUSINE", "TAXI",
                                  "DISPATCH", "SHIPPING")),
    ("automotive", ("AUTO", "AUTOMOTIVE", "MOTORS", "CAR WASH", "COLLISION", "TIRE", "TIRES", "DETAILING",
                    "TOWING", "CARS")),
    ("technology", ("TECH", "TECHNOLOGY", "TECHNOLOGIES", "SOFTWARE", "DIGITAL", "DATA", "AI", "LABS", "SYSTEMS",
                    "CYBER", "CLOUD", "APPS", "IT SERVICES", "COMPUTING", "ANALYTICS", "ROBOTICS", "SAAS")),
    ("financial_services", ("FINANCIAL", "FINANCE", "TAX", "ACCOUNTING", "BOOKKEEPING", "CPA", "LENDING",
                            "MORTGAGE", "WEALTH", "ADVISORS", "PAYMENTS", "CREDIT", "FUNDING")),
    ("insurance", ("INSURANCE", "INSURANCE AGENCY", "ASSURANCE", "UNDERWRITERS")),
    ("legal", ("LAW", "LEGAL", "ATTORNEY", "ATTORNEYS", "ESQ", "PLLC LAW")),
    ("real_estate_services", ("REALTY", "REAL ESTATE", "REALTOR", "REALTORS", "PROPERTY MANAGEMENT", "HOMES",
                              "BROKERAGE", "TITLE")),
    ("marketing_media", ("MARKETING", "MEDIA", "STUDIO", "STUDIOS", "PRODUCTIONS", "PHOTOGRAPHY", "FILMS",
                         "DESIGN", "CREATIVE", "AGENCY", "ADVERTISING", "BRANDING", "PUBLISHING", "MUSIC",
                         "ENTERTAINMENT", "EVENTS")),
    ("consulting", ("CONSULTING", "CONSULTANTS", "CONSULTANCY", "ADVISORY", "STRATEGIES",
                    "MANAGEMENT")),
    ("retail_ecommerce", ("SHOP", "STORE", "BOUTIQUE", "MARKET", "TRADING", "SUPPLY", "SUPPLIES", "GOODS",
                          "APPAREL", "CLOTHING", "JEWELRY", "IMPORTS", "WHOLESALE", "MART", "OUTLET", "BRANDS")),
    ("education", ("ACADEMY", "SCHOOL", "TUTORING", "EDUCATION", "LEARNING", "INSTITUTE", "COACHING")),
    ("hospitality_travel", ("HOTEL", "INN", "MOTEL", "TRAVEL", "TOURS", "VACATION", "LODGE", "HOSPITALITY",
                            "RENTALS", "AIRBNB")),
    ("pets", ("PET", "PETS", "DOG", "CANINE", "VETERINARY", "GROOMING", "K9")),
    ("agriculture", ("FARM", "FARMS", "RANCH", "AGRICULTURE", "ORCHARD", "GARDENS", "GREENHOUSE")),
    ("manufacturing", ("MANUFACTURING", "FABRICATION", "INDUSTRIES", "INDUSTRIAL", "MACHINE", "PRECISION")),
    ("staffing", ("STAFFING", "RECRUITING", "RECRUITMENT", "TALENT", "WORKFORCE", "EMPLOYMENT")),
    ("security", ("SECURITY", "PROTECTION", "GUARD", "ALARM", "SURVEILLANCE")),
]
_INDUSTRY_PATTERNS = [
    (industry, re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b"))
    for industry, keywords in _INDUSTRY_RULES
]
INDUSTRIES = tuple(i for i, _ in _INDUSTRY_RULES)


def classify_industry(name: str) -> str | None:
    upper = _upper_compact(name)
    for industry, pattern in _INDUSTRY_PATTERNS:
        if pattern.search(upper):
            return industry
    return None


# --- Holding vehicles -------------------------------------------------------
# Property SPVs and holding shells are a large share of new LLCs and are noise for
# almost every buyer, so they are flagged and down-scored rather than dropped.
_HOLDING_TOKENS = re.compile(
    r"\b(HOLDINGS?|PROPERTIES|PROPERTY|INVESTMENTS?|CAPITAL|ASSETS|EQUITIES|ACQUISITIONS?|"
    r"REAL ESTATE|SPV|FUND|FUNDS|PORTFOLIO|LAND|PARCEL|FAMILY TRUST|OWNER|OWNERS|LEASING)\b"
)
_ADDRESS_NAME = re.compile(
    r"^\d+[A-Z]?\s+(?:[NSEW]\s+)?[A-Z0-9 ]*\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|LN|LANE|DR|DRIVE|"
    r"PL|PLACE|WAY|CT|COURT|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|CIR|CIRCLE)\b"
)


_LEADING_NUMBER = re.compile(r"^\d{2,6}[A-Z]?\s+[A-Z]")


def is_holding_vehicle(name: str, industry: str | None = None) -> bool:
    upper = _upper_compact(name)
    if _HOLDING_TOKENS.search(upper) or _ADDRESS_NAME.match(upper):
        return True
    # "483 FIRST NECK LLC": a number-led name with no trade keyword is almost always a property SPV.
    return industry is None and bool(_LEADING_NUMBER.match(upper))


# --- Lead score -------------------------------------------------------------
INACTIVE_STATUSES = {
    "DELINQUENT", "WITHDRAWN", "VOLUNTARILY DISSOLVED", "DISSOLVED", "MERGED", "CONVERTED",
    "NONCOMPLIANT", "EFFECTIVENESS PREVENTED", "REVOKED", "INACTIVE",
}


def lead_score(
    *,
    has_business_address: bool,
    has_contact: bool,
    holding: bool,
    industry: str | None,
    is_foreign: bool,
    category: str,
    status: str | None,
) -> int:
    """0-100. Higher = more likely a reachable operating business. Documented in README."""
    score = 40
    score += 20 if has_business_address else 0
    score += 15 if has_contact else 0
    score += 10 if industry else 0
    score += 5 if is_foreign else 0
    score -= 20 if holding else 0
    score -= 10 if category == "nonprofit" else 0
    if status and status.upper() in INACTIVE_STATUSES:
        score -= 30
    return max(0, min(100, score))
