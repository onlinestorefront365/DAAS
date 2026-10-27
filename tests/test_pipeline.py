from dataclasses import replace
from datetime import date, datetime, timezone

from conftest import make_record
from daas.ingest.pipeline import flag_bulk_agents, resolve_since, run_source, upsert_batch
from daas.models import Business, SourceState


class FakeSource:
    code = "test"
    registered_state = "NY"

    def __init__(self, records, fail_after=None):
        self.records = records
        self.fail_after = fail_after

    def fetch(self, since):
        for i, rec in enumerate(self.records):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("upstream died")
            yield rec

    def map(self, row):
        return row


def test_run_source_inserts_then_is_idempotent(session):
    records = [make_record(i) for i in range(5)]
    run = run_source(session, FakeSource(records + [None]), since=date(2026, 1, 1))
    assert (run.status, run.inserted, run.updated, run.skipped) == ("success", 5, 0, 1)
    assert session.get(SourceState, "test").watermark == max(r.formed_on for r in records)

    again = run_source(session, FakeSource(records), since=date(2026, 1, 1))
    assert (again.inserted, again.updated) == (0, 0)

    changed = [replace(records[0], status="Dissolved")]
    third = run_source(session, FakeSource(changed), since=date(2026, 1, 1))
    assert (third.inserted, third.updated) == (0, 1)


def test_failed_run_is_recorded(session):
    run = run_source(session, FakeSource([make_record(1), make_record(2)], fail_after=1), since=date(2026, 1, 1))
    assert run.status == "failed" and "upstream died" in run.error


def test_resolve_since_uses_watermark_minus_lookback(session):
    session.add(SourceState(source="test", watermark=date(2026, 10, 20)))
    session.commit()
    assert resolve_since(session, "test") == date(2026, 10, 13)
    assert resolve_since(session, "test", date(2026, 1, 1)) == date(2026, 1, 1)


def test_upsert_preserves_suppression_and_first_seen(session):
    upsert_batch(session, [make_record(1)])
    session.commit()
    b = session.query(Business).one()
    b.suppressed_at = datetime.now(timezone.utc)
    first_seen, seq = b.first_seen_at, b.seq
    session.commit()

    upsert_batch(session, [make_record(1, name="Renamed LLC")])
    session.commit()
    session.refresh(b)
    assert b.name == "Renamed LLC"
    assert b.suppressed_at is not None and b.first_seen_at == first_seen and b.seq == seq


def test_flag_bulk_agents(session):
    bulk = [
        make_record(i, registered_agent_name="HANNAH PAXTON", contact_name="Hannah Paxton", lead_score=85)
        for i in range(5)
    ]
    solo = make_record(99, registered_agent_name="ARMON LALEH", contact_name="Armon Laleh", lead_score=85)
    upsert_batch(session, bulk + [solo])
    session.commit()

    assert flag_bulk_agents(session) == 5
    rows = {b.source_record_id: b for b in session.query(Business)}
    assert rows["0"].contact_name is None and rows["0"].uses_commercial_agent and rows["0"].lead_score == 70
    assert rows["99"].contact_name == "Armon Laleh" and not rows["99"].uses_commercial_agent
    assert flag_bulk_agents(session) == 0  # idempotent
