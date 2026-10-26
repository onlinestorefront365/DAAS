from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DAAS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/daas"

    # Required for /admin endpoints. Empty disables admin entirely.
    admin_token: str = ""

    # Ingestion
    socrata_app_token: str = ""  # optional; raises Socrata's anonymous throttle
    backfill_days: int = 90  # first run per source pulls this much history
    lookback_days: int = 7  # re-scan window on incremental runs (late-posted filings)
    ingest_page_size: int = 5000
    http_timeout_seconds: float = 60.0

    # Self-serve signup issues a free-plan key. Turn off if abused.
    signup_enabled: bool = True

    # Billing (all optional; billing endpoints return 503 when unset)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_scale: str = ""
    public_base_url: str = "http://localhost:8000"

    # Feed delivery
    feed_batch_size: int = 500
    webhook_timeout_seconds: float = 15.0
    # Tests and local dev deliver to localhost; production must keep this False.
    allow_private_webhooks: bool = False

    # Scheduler
    ingest_interval_minutes: int = 360


@lru_cache
def get_settings() -> Settings:
    return Settings()
