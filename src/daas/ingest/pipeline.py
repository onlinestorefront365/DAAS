import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from daas.config import get_settings
from daas.ingest.base import BusinessRecord, Source
from daas.models import Business, IngestRun, SourceState

log = logging.getLogger(__name__)

BATCH_SIZE = 1000
# Columns ingestion owns. first_seen_at, seq and suppressed_at are never overwritten.
_MUTABLE = [
    c.name
    for c in Business.__table__.columns
    if c.name not in {"id", "seq", "source", "source_record_id", "first_seen_at", "suppressed_at"}
]


def resolve_since(session: Session, source_code: str, override: date | None = None) -> date:
    if override:
        return override
    s = get_settings()
    state = session.get(SourceState, source_code)
    if state and state.watermark:
        return state.watermark - timedelta(days=s.lookback_days)
    return date.today() - timedelta(days=s.backfill_days)


def upsert_batch(session: Session, records: list[BusinessRecord]) -> tuple[int, int]:
    """Insert new rows, update changed rows, leave identical rows alone. Returns (inserted, updated)."""
    if not records:
        return 0, 0
    # Upstream occasionally repeats a row inside one page; Postgres rejects duplicate
    # conflict targets in a single statement, so keep the last occurrence.
    unique = {(r.source, r.source_record_id): r for r in records}
    rows = []
    for rec in unique.values():
        row = asdict(rec)
        row["content_hash"] = rec.content_hash()
        rows.append(row)

    stmt = insert(Business).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_business_source_record",
        set_={**{c: stmt.excluded[c] for c in _MUTABLE}, "updated_at": func.now()},
        where=Business.content_hash.is_distinct_from(stmt.excluded.content_hash),
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    results = session.execute(stmt).scalars().all()
    inserted = sum(1 for r in results if r)
    return inserted, len(results) - inserted


def run_source(session: Session, source: Source, since: date | None = None) -> IngestRun:
    since = resolve_since(session, source.code, since)
    run = IngestRun(source=source.code, since=since, status="running")
    session.add(run)
    session.commit()
    log.info("ingest %s since %s", source.code, since)

    watermark: date | None = None
    batch: list[BusinessRecord] = []
    try:
        for row in source.fetch(since):
            run.fetched += 1
            rec = source.map(row)
            if rec is None:
                run.skipped += 1
                continue
            watermark = max(watermark, rec.formed_on) if watermark else rec.formed_on
            batch.append(rec)
            if len(batch) >= BATCH_SIZE:
                ins, upd = upsert_batch(session, batch)
                run.inserted += ins
                run.updated += upd
                batch.clear()
                session.commit()
        ins, upd = upsert_batch(session, batch)
        run.inserted += ins
        run.updated += upd

        state = session.get(SourceState, source.code) or SourceState(source=source.code)
        if watermark and (state.watermark is None or watermark > state.watermark):
            state.watermark = watermark
        state.last_success_at = datetime.now(timezone.utc)
        session.add(state)
        run.status = "success"
    except Exception as exc:
        session.rollback()
        run = session.merge(run)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        log.exception("ingest %s failed", source.code)
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    log.info(
        "ingest %s %s fetched=%s inserted=%s updated=%s skipped=%s",
        source.code, run.status, run.fetched, run.inserted, run.updated, run.skipped,
    )
    return run


def rescore_all(session: Session, sources: dict[str, Source]) -> int:
    """Re-run mapping/enrichment over stored raw rows after rule changes."""
    total = 0
    last_seq = 0
    while True:
        rows = session.execute(
            select(Business.seq, Business.source, Business.raw)
            .where(Business.seq > last_seq)
            .order_by(Business.seq)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            return total
        records = []
        for seq, source_code, raw in rows:
            last_seq = seq
            src = sources.get(source_code)
            rec = src.map(raw) if src else None
            if rec:
                records.append(rec)
        _, updated = upsert_batch(session, records)
        total += updated
        session.commit()


BULK_AGENT_THRESHOLD = 5


def flag_bulk_agents(session: Session, threshold: int = BULK_AGENT_THRESHOLD) -> int:
    """Agents on many filings in a year are formation services, not founders, even when
    they're an unknown name or an individual. Un-credit them as contacts and lead signals.

    Runs after every ingest/rescore because the signal depends on volume across records.
    """
    result = session.execute(
        text(
            """
            WITH bulk AS (
                SELECT source, upper(registered_agent_name) AS agent
                FROM businesses
                WHERE registered_agent_name IS NOT NULL AND formed_on >= current_date - 365
                GROUP BY 1, 2
                HAVING count(*) >= :threshold
            )
            UPDATE businesses b
            SET uses_commercial_agent = true,
                lead_score = greatest(0, b.lead_score - CASE WHEN b.contact_name IS NOT NULL
                    AND upper(b.contact_name) = bulk.agent THEN 15 ELSE 0 END),
                contact_name = CASE WHEN upper(b.contact_name) = bulk.agent THEN NULL ELSE b.contact_name END
            FROM bulk
            WHERE b.source = bulk.source AND upper(b.registered_agent_name) = bulk.agent
              AND NOT b.uses_commercial_agent
            """
        ),
        {"threshold": threshold},
    )
    session.commit()
    return result.rowcount


def mark_stale_runs(session: Session) -> None:
    """A crashed worker leaves runs in 'running'; close them so coverage stats stay honest."""
    session.execute(
        update(IngestRun)
        .where(IngestRun.status == "running", IngestRun.started_at < func.now() - timedelta(hours=6))
        .values(status="failed", error="abandoned", finished_at=func.now())
    )
    session.commit()
