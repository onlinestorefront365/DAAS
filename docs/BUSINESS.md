# Business plan: New Business Leads

## The bet

Newly formed businesses are the highest-intent B2B buyers that exist. In their first 90 days they choose a bank, insurer, payroll provider, accountant, POS, website and phone system, and most of those choices stick for years. The signal is public (state filings) but scattered, unnormalized, and full of noise: formation-service addresses, holding shells, placeholders. **We sell the cleaned, scored, same-week version through an API and a webhook feed.**

## Who pays (ICP, in order of attack)

1. **Vertical SaaS and fintech outbound teams** selling to SMBs: payroll (Gusto-style), POS and merchant services, business banking, bookkeeping, website builders. They need volume plus freshness and already buy lists.
2. **Commercial insurance agencies and brokers.** Every new LLC with employees needs workers' comp and general liability. Local and regional agencies pay well for their zip codes.
3. **Local service providers**: CPAs, attorneys, sign shops, commercial cleaners. They want small, cheap, recurring volume and are served by Starter plus feeds.
4. **Data and lead-gen agencies** that resell. This is a later channel with a separate wholesale contract.

Wedge: **trades and construction in CO, plus NY metro service businesses.** These have high LTV for insurance and payroll buyers, and the industry classifier is strongest there.

## Why us, why now

- Incumbents (D&B, ZoomInfo, Data Axle) are slow on day-0 entities. A business filed yesterday isn't in their graph for months.
- Cheap lead lists from scrapers are raw dumps: they include formation-agent addresses, they don't separate holding SPVs from operating companies, and there's no API or feed.
- Our product is the cleaning plus the delivery mechanism (webhooks into CRMs). The data itself is free, and that's the point: our margin is the engineering, not a licence.

## Pricing

| Plan | $/mo | Records | Who |
|---|---|---|---|
| Free | 0 | 100 | Lead magnet. Proves data quality in one call. |
| Starter | 99 | 5k | Local agencies and service businesses |
| Growth | 299 | 25k + CSV + 5 feeds | SMB sales teams |
| Scale | 799 | 100k + 25 feeds | SaaS outbound teams, multi-region agencies |
| Enterprise | custom | bulk + SLA | Resellers, data teams |

Price is per record delivered, not per request, so a buyer only pays for what they actually take. Annual prepay is 2 months free.

## Unit economics (target)

- COGS is close to zero: open data, plus one Postgres instance and one container, roughly $50–150/mo up to around 10M rows.
- Gross margin is above 90%.
- Break-even on infra and tools comes at about 2 Starter customers. **$10k MRR ≈ 25 Growth + 8 Scale customers.**

## Go-to-market (first 90 days)

1. **Week 1–2: proof assets.**
   - A public `/v1/coverage` page.
   - A weekly "New businesses in Denver" post on LinkedIn and in local subreddits, generated from the API.
   - A free tier with self-serve signup.
2. **Week 2–6: founder-led sales.**
   - Run cold email to 300 insurance agencies and 200 SMB-focused SaaS sales leaders, built from our own data plus their public sites.
   - The offer is a free 2-week feed of their exact ICP into their CRM.
   - Conversion is measured as feed created → paid.
3. **Week 4–8: integrations that create lock-in.**
   - A Zapier and Make app (trigger: new matching business).
   - A HubSpot and Salesforce push.
   - Once leads arrive in their CRM daily, churn is low.
4. **Week 6–12: expand coverage on demand.**
   - Add states in the order paying customers ask for them. FL (daily SFTP bulk files), TX, CA and WA are the high-volume next targets.

**Success metric:** 10 paying customers and less than 5% monthly logo churn by day 90. Don't add states nobody has paid for.

## Moat (what compounds)

1. **History.** Every day ingested is a day a new competitor can't backfill cheaply once states rotate or trim their datasets.
2. **Labels.** Customer feedback (bounced, converted, wrong industry) trains better scoring and industry models. That feedback loop is ours alone.
3. **Enrichment layers.** These are the next build, in priority order:
   - Domain and website discovery
   - Phone via licensed providers
   - Employer-ID / hiring signals
   - Status changes (dissolutions = churn signal for existing vendors)
4. **Distribution.** CRM and Zapier integrations make us infrastructure, not a list.

## Risks and how we handle them

| Risk | Handling |
|---|---|
| **Privacy / data-broker laws.** A founder's name and a principal address that is often a home address are personal information. California (Delete Act; DROP deletion requests from Aug 2026), Vermont, Texas and Oregon require data-broker registration and deletion handling. | Register as a data broker in those states **before the first paid customer**. Removal requests are honored through `/admin/businesses/{id}/suppress`, and suppression survives re-ingestion. Add a public removal-request form. Phone numbers and personal emails are kept out until there's a TCPA/CAN-SPAM-reviewed policy. |
| Buyer misuse (spam) | ToS requires CAN-SPAM-compliant outreach and bans resale below Enterprise. Keys can be disabled per customer. |
| Source changes or rate limits | Sources are official open-data APIs, not scraping. Get a Socrata app token, monitor ingest-run failures, and add states to reduce dependence on any single source. |
| Low-quality free-tier abuse | Free plan is 100 records and 30 days of history. Signup can be closed with `DAAS_SIGNUP_ENABLED=false`. |
| Competitors copy the free data | Expected. The defensibility is in the cleaning rules, history, feedback labels and integrations, not the raw data. |

## Next engineering priorities

1. Florida connector (largest formation volume in the US).
2. Domain/website discovery enrichment (biggest jump in lead value).
3. Zapier/HubSpot integration.
4. Customer feedback endpoint (`POST /v1/businesses/{id}/feedback`) to start collecting labels.
5. A simple dashboard (signup, keys, usage, feed setup) for non-technical buyers.
