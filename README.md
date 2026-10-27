# New Business Leads API

A data-as-a-service engine that turns official state business filings into scored B2B leads and sells them through a metered subscription API.

Every day thousands of companies register with a Secretary of State. In their first 90 days they buy insurance, payroll, banking, a POS system, accounting, a website, signage and software. Whoever reaches them first wins. This engine:

1. **Ingests** new filings daily from official open-data publications (NY and CO at launch).
2. **Normalizes and enriches** each filing: entity type, industry, founder/contact name, real business address versus registered-agent address, holding-vehicle detection, and a 0–100 lead score.
3. **Sells access** through an API-key-authenticated REST API with plan tiers, rate limits, monthly record quotas, CSV export, webhook feeds and Stripe billing.

The business plan (who pays, pricing, go-to-market, risks) is in [`docs/BUSINESS.md`](docs/BUSINESS.md).

## Quickstart

```bash
cp .env.example .env            # set DAAS_ADMIN_TOKEN at minimum
docker compose up --build       # postgres + migrations + api + scheduler worker
```

Or run it locally against your own Postgres 14+:

```bash
make install
export DAAS_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/daas
.venv/bin/daas migrate
.venv/bin/daas ingest --since 2026-10-01     # first real pull, ~10k rows per 10 days
.venv/bin/daas create-customer --email you@example.com --plan growth
.venv/bin/daas serve
```

The interactive docs are at `http://localhost:8000/docs`.

## API

Send the key as `Authorization: Bearer dk_live_...` or as `X-API-Key`.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/businesses` | Search, newest first, cursor-paginated. Metered per record. |
| `GET` | `/v1/businesses/{id}` | Single record. Metered. |
| `GET` | `/v1/businesses/export.csv` | Up to 10k rows, for CRM import. Growth and Scale plans only. |
| `POST/GET/PATCH/DELETE` | `/v1/feeds` | Saved searches pushed to your webhook as new filings land. |
| `GET` | `/v1/account` | Plan, usage this month, remaining quota. |
| `GET/POST/DELETE` | `/v1/account/keys` | Rotate keys (up to 5 active). |
| `POST` | `/v1/billing/checkout` | Returns a Stripe Checkout URL for `starter`, `growth` or `scale`. |
| `POST` | `/v1/billing/portal` | Stripe customer portal URL. |
| `POST` | `/v1/signup` | Self-serve free plan. Returns a key once. |
| `GET` | `/v1/plans`, `/v1/coverage` | Public. |

Search filters: `state`, `formed_after`, `formed_before`, `entity_category`, `industry`, `region`, `city`, `postal_code`, `county`, `q` (fuzzy name), `min_score`, `has_contact`, `has_address`, `is_foreign`, `exclude_holding`. List filters accept either repeated params or commas (`state=NY,CO`).

```bash
curl -H "Authorization: Bearer $KEY" \
  "localhost:8000/v1/businesses?state=CO&industry=construction_trades&min_score=75&exclude_holding=true"
```

### Feeds (webhooks)

A feed holds a filter set and an HTTPS URL. After each ingest, new matching records are POSTed in batches of up to 500:

```json
{"feed_id": "...", "count": 2, "data": [ { ...business... } ]}
```

Verify the `X-DaaS-Signature: t=<unix>,v1=<hex>` header, where `v1` is `HMAC_SHA256(feed.secret, "<t>." + raw_body)`. Any non-2xx response holds the cursor and the batch is retried next cycle. After 10 consecutive failures the feed is disabled. Delivered records count toward the quota.

### Admin

Admin endpoints need the `X-Admin-Token` header and are hidden from the public docs:

- `GET/POST /admin/customers`
- `PATCH /admin/customers/{id}`
- `POST /admin/customers/{id}/keys`
- `POST /admin/businesses/{id}/suppress` (handles removal requests)
- `GET /admin/ingest-runs`

## Plans

Plans are defined in `src/daas/plans.py`. Prices themselves live in Stripe.

| Plan | $/mo | Records/mo | Req/min | Feeds | CSV | History |
|---|---|---|---|---|---|---|
| Free | 0 | 100 | 10 | 0 | – | 30 days |
| Starter | 99 | 5,000 | 60 | 1 | – | 1 year |
| Growth | 299 | 25,000 | 120 | 5 | ✓ | full |
| Scale | 799 | 100,000 | 300 | 25 | ✓ | full |

Quota is counted in **records returned**, not requests, so a customer pays for the data they actually take. A request that would exceed the quota is clamped to what remains. Once nothing remains the API returns `402` with an upgrade hint.

For Stripe, create the three prices, set `DAAS_STRIPE_PRICE_*`, and point a webhook at `/billing/webhook` with these events:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

## Data

| Source | Publisher | Dataset | Volume (2026 YTD) |
|---|---|---|---|
| `ny_dos` | NY Department of State | [data.ny.gov n9v6-gdp6](https://data.ny.gov/d/n9v6-gdp6) | ~225k new entities |
| `co_sos` | Colorado Secretary of State | [data.colorado.gov 4ykn-tg5h](https://data.colorado.gov/d/4ykn-tg5h), public domain | ~170k new entities |

Ingestion is incremental. Each run re-scans `watermark − 7 days` to catch late-posted filings, upserts on `(source, source_record_id)`, and only rewrites rows whose content hash changed. Suppressed rows stay suppressed through re-ingestion.

### Enrichment

The rules live in `src/daas/enrichment.py`. All of them are deterministic, so `daas rescore` reapplies new rules to the whole archive from the stored raw rows.

- **Commercial registered agents** (Northwest, LegalZoom, CT Corp and about 40 others) are detected so their office address is never sold as the business address.
- **Bulk agents:** any agent on 5 or more filings in a year is also treated as a filing service, even when it's an unknown person.
- **Contact name** comes from the NY chairman or process recipient, or the CO individual registered agent, and only when it looks like a person.
- **Industry** is a keyword classifier tuned for precision. About 30% of names get a label, and the rest stay null rather than guessed.
- **Holding vehicles** (Holdings, Properties, `123 Main St LLC`, …) are flagged rather than dropped.

The lead score (0–100) starts at 40, then:

| Signal | Points |
|---|---|
| Real business address | +20 |
| Contact name | +15 |
| Industry identified | +10 |
| Out-of-state company expanding in | +5 |
| Holding vehicle | −20 |
| Nonprofit | −10 |
| Inactive status | −30 |

On the first live pull (10 days, 10,858 filings), 32% scored 75 or higher.

### Adding a state

To add a state, subclass `SocrataSource` (or implement the `Source` protocol for non-Socrata sources such as Florida's SFTP bulk files) in `src/daas/ingest/sources.py`, map rows to `BusinessRecord`, register the class in `SOURCES`, and add fixture-based tests.

## Operations

- `daas scheduler` runs one cycle every `DAAS_INGEST_INTERVAL_MINUTES`: ingest all sources, flag bulk agents, deliver feeds, then clean up rate-limit windows.
- Rate limiting is a fixed one-minute window kept in Postgres, so the stack has no Redis dependency. Move it to Redis past roughly 500 req/s.
- Webhook URLs are checked for HTTPS and public IPs both when a feed is created and on every delivery (SSRF guard).

## Development

```bash
make install
createdb daas_test        # tests run against real Postgres
make test
```

Set `DAAS_TEST_DATABASE_URL` to use a different test database. CI (`.github/workflows/ci.yml`) runs the suite and checks that migrations apply cleanly on a fresh database.
