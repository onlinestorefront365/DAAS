import argparse
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select

from daas.db import get_sessionmaker

log = logging.getLogger("daas")


def _migrate(_: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    # Works from a checkout (repo root) or from the container's /app.
    root = next(
        (d for d in (Path.cwd(), Path(__file__).resolve().parents[2]) if (d / "alembic.ini").exists()),
        Path.cwd(),
    )
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")


def _ingest(args: argparse.Namespace) -> int:
    from daas.ingest.pipeline import flag_bulk_agents, mark_stale_runs, run_source
    from daas.ingest.sources import SOURCES

    codes = args.source or list(SOURCES)
    since = date.fromisoformat(args.since) if args.since else None
    failed = 0
    with get_sessionmaker()() as session:
        mark_stale_runs(session)
        for code in codes:
            run = run_source(session, SOURCES[code](), since)
            failed += run.status != "success"
        log.info("flagged %s rows filed by bulk agents", flag_bulk_agents(session))
    return 1 if failed else 0


def _rescore(_: argparse.Namespace) -> None:
    from daas.ingest.pipeline import flag_bulk_agents, rescore_all
    from daas.ingest.sources import SOURCES

    with get_sessionmaker()() as session:
        print(f"updated {rescore_all(session, {c: cls() for c, cls in SOURCES.items()})} rows")
        print(f"flagged {flag_bulk_agents(session)} rows filed by bulk agents")


def _deliver(_: argparse.Namespace) -> None:
    from daas.feeds import deliver_all

    with get_sessionmaker()() as session:
        print(deliver_all(session))


def _housekeeping() -> None:
    from daas.models import RateLimitWindow

    with get_sessionmaker()() as session:
        session.execute(
            delete(RateLimitWindow).where(RateLimitWindow.window_start < func.now() - timedelta(hours=1))
        )
        session.commit()


def _scheduler(args: argparse.Namespace) -> None:
    from daas.config import get_settings

    interval = get_settings().ingest_interval_minutes * 60
    while True:
        started = time.monotonic()
        try:
            _ingest(argparse.Namespace(source=None, since=None))
            _deliver(args)
            _housekeeping()
        except Exception:
            log.exception("scheduler cycle failed")
        time.sleep(max(60, interval - (time.monotonic() - started)))


def _create_customer(args: argparse.Namespace) -> None:
    from daas.api.routes.account import issue_key
    from daas.models import Customer

    with get_sessionmaker()() as session:
        if session.scalar(select(Customer).where(func.lower(Customer.email) == args.email.lower())):
            raise SystemExit("customer exists")
        customer = Customer(email=args.email.lower(), company=args.company, plan=args.plan)
        session.add(customer)
        session.flush()
        key = issue_key(session, customer)
        session.commit()
        print(json.dumps({"customer_id": str(customer.id), "api_key": key.api_key}))


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("daas.api.app:app", host=args.host, port=args.port, workers=args.workers)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="daas")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="Apply database migrations").set_defaults(fn=_migrate)

    p = sub.add_parser("ingest", help="Pull new filings from state sources")
    p.add_argument("--source", action="append", help="Source code (repeatable); default all")
    p.add_argument("--since", help="YYYY-MM-DD; overrides the stored watermark")
    p.set_defaults(fn=_ingest)

    sub.add_parser("rescore", help="Re-apply enrichment rules to stored records").set_defaults(fn=_rescore)
    sub.add_parser("deliver-feeds", help="Push new matches to customer webhooks").set_defaults(fn=_deliver)
    sub.add_parser("scheduler", help="Loop: ingest, deliver feeds, housekeeping").set_defaults(fn=_scheduler)

    p = sub.add_parser("create-customer", help="Create a customer and print its first API key")
    p.add_argument("--email", required=True)
    p.add_argument("--company")
    p.add_argument("--plan", default="free", choices=["free", "starter", "growth", "scale"])
    p.set_defaults(fn=_create_customer)

    p = sub.add_parser("serve", help="Run the API")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=2)
    p.set_defaults(fn=_serve)

    args = parser.parse_args(argv)
    raise SystemExit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
