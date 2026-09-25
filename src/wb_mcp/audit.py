"""Read-only advertising audit: zone efficiency, wasteful clusters, weak campaigns.

Encodes the manual audit flow: WB fullstats has no per-zone split, so the search
share comes from search-cluster stats and everything else (recommendations plus
catalog) is the campaign total minus search. Orders are valued at the campaign's
average order price. Nothing here writes to WB; callers turn the suggestions into
wb_plan_update_placements / wb_plan_update_minus_phrases / pause plans.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from datetime import date, timedelta
from typing import Final

from .gateway import WBError

Reader = Callable[[str, dict[str, object]], dict[str, object]]

BAD_CHANNEL_DRR: Final = 20.0
MIN_CHANNEL_SPEND: Final = 500.0
MIN_CAMPAIGN_SPEND: Final = 1000.0
HIGH_CAMPAIGN_DRR: Final = 25.0
HIGH_DRR_MIN_SPEND: Final = 5000.0
NO_ORDERS_MIN_SPEND: Final = 3000.0
CLUSTER_MIN_SPEND: Final = 700.0
CLUSTER_CPO_SHARE: Final = 0.8
NEW_CAMPAIGN_DAYS: Final = 7
STATS_CHUNK: Final = 50
CLUSTER_CHUNK: Final = 100
# ponytail: fullstats allows ~1 call/min; wait out 429s instead of failing the audit.
RATE_LIMIT_WAIT_SECONDS: Final = 20.0
RATE_LIMIT_RETRIES: Final = 4

RULES: Final = {
    "zone_source": "search = cluster stats; rest = total - search (recs + catalog)",
    "channel_bad": (
        f"spend >= {MIN_CHANNEL_SPEND:.0f} and "
        f"(0 orders or DRR > {BAD_CHANNEL_DRR:.0f}%)"
    ),
    "channel_good": f"orders > 0 and DRR <= {BAD_CHANNEL_DRR:.0f}%",
    "disable_channel": "one channel bad, the other good",
    "both_weak": "both channels bad: review clusters/bids or pause",
    "cluster_candidate": (
        f"0 orders, spend >= max({CLUSTER_MIN_SPEND:.0f}, "
        f"{CLUSTER_CPO_SHARE} * campaign search CPO), not yet a minus phrase"
    ),
    "new_campaign": f"created < {NEW_CAMPAIGN_DAYS} days before date_to: thin data",
}


def _pick(mapping: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _map(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _chunks(items: list[object], size: int) -> Iterable[list[object]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _read_patiently(
    read: Reader,
    operation: str,
    payload: dict[str, object],
    sleep: Callable[[float], None],
) -> dict[str, object]:
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return read(operation, payload)
        except WBError as error:
            if error.kind != "rate_limited" or attempt == RATE_LIMIT_RETRIES:
                raise
            sleep(RATE_LIMIT_WAIT_SECONDS)
    raise AssertionError("unreachable")


def _drr(spend: float, orders: float, avg_price: float) -> float | None:
    if orders <= 0 or avg_price <= 0:
        return None
    return round(spend / (orders * avg_price) * 100, 1)


def _channel(spend: float, orders: float, avg_price: float) -> dict[str, object]:
    drr = _drr(spend, orders, avg_price)
    bad = spend >= MIN_CHANNEL_SPEND and (orders <= 0 or (drr or 0) > BAD_CHANNEL_DRR)
    good = orders > 0 and drr is not None and drr <= BAD_CHANNEL_DRR
    return {
        "spend": round(spend),
        "orders": round(orders),
        "drr": drr,
        "state": "bad" if bad else "good" if good else "unclear",
    }


def zone_verdict(search: Mapping[str, object], rest: Mapping[str, object]) -> str:
    """Decide which channel to keep from two _channel() results."""

    s, r = search["state"], rest["state"]
    if s == "bad" and r == "good":
        return "disable_search"
    if r == "bad" and s == "good":
        return "disable_recommendations"
    if s == "bad" and r == "bad":
        return "both_weak"
    return "keep_both"


def audit(
    read: Reader,
    date_from: date,
    date_to: date,
    campaign_ids: list[int] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Collect stats for active campaigns and return audit findings."""

    listing: dict[str, object] = (
        {"campaign_ids": campaign_ids} if campaign_ids else {"statuses": [9]}
    )
    adverts = [
        a
        for a in _list(read("list_campaigns", listing).get("adverts"))
        if isinstance(a, Mapping) and a.get("status") == 9
    ]
    campaigns: dict[int, Mapping[str, object]] = {}
    for advert in adverts:
        advert_id = advert.get("id")
        if isinstance(advert_id, int):
            campaigns[advert_id] = advert
    if not campaigns:
        return {"period": [str(date_from), str(date_to)], "campaigns": 0}

    stats: dict[int, Mapping[str, object]] = {}
    for chunk in _chunks(list(campaigns), STATS_CHUNK):
        payload: dict[str, object] = {
            "campaign_ids": chunk,
            "date_from": date_from,
            "date_to": date_to,
        }
        response = _read_patiently(read, "campaign_stats", payload, sleep)
        for row in _list(response.get("data")):
            row = _map(row)
            advert_id = row.get("advertId")
            if isinstance(advert_id, int):
                stats[advert_id] = row

    pairs: list[object] = []
    nm_of: dict[int, int] = {}
    for advert_id, advert in campaigns.items():
        settings = advert.get("nm_settings")
        # ponytail: first product only; multi-product campaigns need per-nm pairs.
        if isinstance(settings, list) and settings and isinstance(settings[0], Mapping):
            nm_id = settings[0].get("nm_id")
            if isinstance(nm_id, int):
                nm_of[advert_id] = nm_id
                pairs.append({"campaign_id": advert_id, "nm_id": nm_id})

    clusters: dict[int, dict[str, dict[str, float]]] = {}
    minus: dict[int, set[str]] = {}
    for chunk in _chunks(pairs, CLUSTER_CHUNK):
        payload = {"date_from": date_from, "date_to": date_to, "items": chunk}
        response = _read_patiently(read, "search_cluster_stats", payload, sleep)
        for item in _list(response.get("items") or response.get("stats")):
            item = _map(item)
            advert_id = _pick(item, "advertId", "advert_id")
            if not isinstance(advert_id, int):
                continue
            per_query = clusters.setdefault(advert_id, {})
            for day in _list(_pick(item, "dailyStats", "daily_stats")):
                stat = _map(day).get("stat")
                if not isinstance(stat, Mapping):
                    continue
                query = str(_pick(stat, "normQuery", "norm_query") or "")
                acc = per_query.setdefault(
                    query, {"spend": 0.0, "orders": 0.0, "clicks": 0.0, "atbs": 0.0}
                )
                for key in acc:
                    acc[key] += _num(stat.get(key))
        minus_response = _read_patiently(read, "minus_phrases", {"items": chunk}, sleep)
        for item in _list(minus_response.get("items")):
            item = _map(item)
            advert_id = item.get("advert_id")
            if isinstance(advert_id, int):
                minus[advert_id] = {str(q) for q in _list(item.get("norm_queries"))}

    new_since = date_to - timedelta(days=NEW_CAMPAIGN_DAYS)
    total_spend = total_revenue = total_orders = 0.0
    zones: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    flags: list[dict[str, object]] = []
    cluster_candidates: list[dict[str, object]] = []
    placements_plan: list[dict[str, object]] = []

    for advert_id, advert in campaigns.items():
        row = stats.get(advert_id, {})
        spend, revenue, orders = (
            _num(row.get("sum")),
            _num(row.get("sum_price")),
            _num(row.get("orders")),
        )
        total_spend += spend
        total_revenue += revenue
        total_orders += orders
        settings = _map(advert.get("settings"))
        name = str(settings.get("name", ""))
        created = str(_map(advert.get("timestamps")).get("created") or "")[:10]
        is_new = bool(created) and created > new_since.isoformat()
        avg_price = revenue / orders if orders else 0.0
        base = {"campaign_id": advert_id, "name": name, "new": is_new}

        drr = _drr(spend, orders, avg_price)
        if orders <= 0 and spend >= NO_ORDERS_MIN_SPEND:
            flags.append({**base, "flag": "no_orders", "spend": round(spend)})
        elif (
            drr is not None and drr > HIGH_CAMPAIGN_DRR and spend >= HIGH_DRR_MIN_SPEND
        ):
            flags.append(
                {**base, "flag": "high_drr", "spend": round(spend), "drr": drr}
            )

        per_query = clusters.get(advert_id, {})
        s_spend = sum(q["spend"] for q in per_query.values())
        s_orders = sum(q["orders"] for q in per_query.values())
        s_cpo = s_spend / s_orders if s_orders else 0.0
        threshold = max(CLUSTER_MIN_SPEND, CLUSTER_CPO_SHARE * s_cpo)
        excluded = minus.get(advert_id, set())
        for query, q in per_query.items():
            if q["orders"] == 0 and q["spend"] >= threshold and query not in excluded:
                cluster_candidates.append(
                    {
                        **base,
                        "nm_id": nm_of.get(advert_id),
                        "norm_query": query,
                        "spend": round(q["spend"]),
                        "clicks": round(q["clicks"]),
                        "atbs": round(q["atbs"]),
                        "search_cpo": round(s_cpo),
                    }
                )

        placements = _map(settings.get("placements"))
        both_on = bool(placements.get("search") and placements.get("recommendations"))
        if not both_on:
            continue
        if settings.get("payment_type") != "cpm" or advert.get("bid_type") != "manual":
            skipped.append(
                {**base, "reason": "zones are not separable (unified bid or CPC)"}
            )
            continue
        if spend < MIN_CAMPAIGN_SPEND:
            skipped.append({**base, "reason": "spend too small"})
            continue
        search = _channel(s_spend, s_orders, avg_price)
        rest = _channel(
            max(spend - s_spend, 0.0), max(orders - s_orders, 0.0), avg_price
        )
        verdict = zone_verdict(search, rest)
        zones.append({**base, "search": search, "rest": rest, "verdict": verdict})
        if verdict in ("disable_search", "disable_recommendations"):
            placements_plan.append(
                {
                    "campaign_id": advert_id,
                    "search": verdict != "disable_search",
                    "recommendations": verdict != "disable_recommendations",
                }
            )

    zones.sort(
        key=lambda z: (
            str(z["verdict"]),
            -_num(_map(z["search"]).get("spend")) - _num(_map(z["rest"]).get("spend")),
        )
    )
    cluster_candidates.sort(key=lambda c: -_num(c["spend"]))
    return {
        "period": [str(date_from), str(date_to)],
        "campaigns": len(campaigns),
        "totals": {
            "spend": round(total_spend),
            "revenue": round(total_revenue),
            "orders": round(total_orders),
            "drr": _drr(total_spend, 1, total_revenue) if total_revenue else None,
        },
        "zones": zones,
        "suggested_placements": {"campaigns": placements_plan},
        "cluster_candidates": cluster_candidates,
        "campaign_flags": flags,
        "skipped": skipped,
        "rules": RULES,
    }
