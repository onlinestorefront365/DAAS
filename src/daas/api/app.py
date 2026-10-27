import logging

from fastapi import FastAPI

from daas.api.routes import account, admin, billing, businesses, feeds, meta

DESCRIPTION = """
Newly registered US businesses from official state filings, normalized and scored
for B2B prospecting. Authenticate with `Authorization: Bearer <api key>`.

Each business record returned (search, lookup, export, or feed delivery) counts
toward your plan's monthly record quota.
"""


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(title="New Business Leads API", version="1.0.0", description=DESCRIPTION)
    for module in (meta, account, businesses, feeds, billing, admin):
        app.include_router(module.router)
    return app


app = create_app()
