import os

os.environ["DAAS_DATABASE_URL"] = os.environ.get(
    "DAAS_TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/daas_test"
)
os.environ["DAAS_ADMIN_TOKEN"] = "test-admin"
os.environ["DAAS_ALLOW_PRIVATE_WEBHOOKS"] = "true"
os.environ["DAAS_STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["DAAS_STRIPE_PRICE_STARTER"] = "price_starter"
os.environ["DAAS_STRIPE_PRICE_GROWTH"] = "price_growth"
os.environ["DAAS_STRIPE_PRICE_SCALE"] = "price_scale"

import json  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from daas.db import get_engine, get_sessionmaker  # noqa: E402
from daas.ingest.base import BusinessRecord  # noqa: E402
from daas.ingest.pipeline import upsert_batch  # noqa: E402
from daas.models import Base, Customer  # noqa: E402
from daas.security import generate_api_key  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="session", autouse=True)
def schema():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session():
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def client():
    from daas.api.app import app

    return TestClient(app)


@pytest.fixture
def make_customer(session):
    def _make(plan: str = "growth", email: str | None = None) -> tuple[Customer, str]:
        customer = Customer(email=email or f"{plan}-{os.urandom(4).hex()}@example.com", plan=plan)
        session.add(customer)
        session.flush()
        from daas.models import ApiKey

        plaintext, prefix, digest = generate_api_key()
        session.add(ApiKey(customer_id=customer.id, prefix=prefix, key_hash=digest))
        session.commit()
        return customer, plaintext

    return _make


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def make_record(i: int, **overrides) -> BusinessRecord:
    base = dict(
        source="test",
        source_record_id=str(i),
        registered_state="NY",
        name=f"Acme {i} Plumbing LLC",
        name_normalized=f"acme {i} plumbing",
        entity_type_raw="DOMESTIC LIMITED LIABILITY COMPANY",
        entity_category="llc",
        is_professional=False,
        is_foreign=False,
        home_jurisdiction="NY",
        status="Active",
        formed_on=date.today() - timedelta(days=i % 20),
        street1="1 Main St",
        street2=None,
        city="Albany",
        region="NY",
        postal_code="12207",
        country="US",
        county="Albany",
        address_kind="process",
        contact_name="Jane Doe",
        registered_agent_name=None,
        uses_commercial_agent=False,
        industry="construction_trades",
        is_holding_vehicle=False,
        lead_score=85,
        raw={"i": i},
    )
    base.update(overrides)
    return BusinessRecord(**base)


@pytest.fixture
def seed(session):
    def _seed(records: list[BusinessRecord]) -> None:
        upsert_batch(session, records)
        session.commit()

    return _seed
