"""Subscription tiers. Limits are enforced in the API; prices live in Stripe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly_price_usd: int
    monthly_records: int  # business records returned or delivered per calendar month (UTC)
    requests_per_minute: int
    max_feeds: int
    csv_export: bool
    history_days: int | None  # how far back `formed_on` may reach; None = full archive


PLANS: dict[str, Plan] = {
    p.code: p
    for p in [
        Plan("free", "Free", 0, 100, 10, 0, False, 30),
        Plan("starter", "Starter", 99, 5_000, 60, 1, False, 365),
        Plan("growth", "Growth", 299, 25_000, 120, 5, True, None),
        Plan("scale", "Scale", 799, 100_000, 300, 25, True, None),
    ]
}

PAID_PLANS = ("starter", "growth", "scale")


def get_plan(code: str) -> Plan:
    return PLANS.get(code, PLANS["free"])
