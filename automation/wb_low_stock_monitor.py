#!/usr/bin/env python3
"""Report low-stock products with active, materially spending WB campaigns."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

try:
    from .wb_common import (
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
        nested_items,
        rows,
    )
    from .wb_mcp_client import MCPClientError, WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
        nested_items,
        rows,
    )
    from wb_mcp_client import MCPClientError, WBMCPClient  # type: ignore[no-redef]

DEFAULT_DB = Path("/root/.hermes/data/wb_adv_stats.db")
BUDGET_STOCK_LIMIT = 50
MIN_WEEK_SPEND = 500


def _stock_products(client: MCPCaller, today: date) -> list[dict[str, object]]:
    start = today - timedelta(days=30)
    items: list[dict[str, object]] = []
    offset = 0
    while True:
        result = call_with_retry(
            client,
            "wb_get_stock_products",
            {
                "date_from": start.isoformat(),
                "date_to": today.isoformat(),
                "stock_type": "",
                "skip_deleted_nm": True,
                "order_field": "stockCount",
                "order_mode": "asc",
                "availability_filters": [],
                "offset": offset,
                "limit": 1000,
            },
        )
        page = nested_items(result)
        items.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return items


def _weekly_spend(db_path: str | Path) -> dict[int, float]:
    try:
        with sqlite3.connect(db_path) as connection:
            result = connection.execute(
                """
                SELECT advert_id, SUM(spend)
                FROM adv_daily
                WHERE date >= date('now','-7 days')
                GROUP BY advert_id
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {int(campaign_id): float(spend) for campaign_id, spend in result}


def collect_candidates(
    client: MCPCaller,
    *,
    db_path: str | Path = DEFAULT_DB,
    today: date | None = None,
) -> list[dict[str, object]]:
    selected_date = today or date.today()
    products = _stock_products(client, selected_date)
    nm_stock: defaultdict[int, int] = defaultdict(int)
    nm_info: dict[int, dict[str, str]] = {}
    for product in products:
        nm_id = as_int(product.get("nmID"))
        if not nm_id:
            continue
        metrics = mapping(product.get("metrics"))
        nm_stock[nm_id] += as_int(metrics.get("stockCount"))
        nm_info.setdefault(
            nm_id,
            {
                "name": str(product.get("name", "?")),
                "article": str(product.get("vendorCode", "?")),
            },
        )

    candidates: list[dict[str, object]] = []
    for nm_id, stock in nm_stock.items():
        if stock <= 0 or stock > BUDGET_STOCK_LIMIT:
            continue
        info = nm_info.get(nm_id, {})
        candidates.append(
            {
                "nmId": nm_id,
                "name": info.get("name", "?"),
                "article": info.get("article", "?"),
                "stock": stock,
                "stock_sum": 0,
                "orders_30d": 0,
                "avg_orders_day": 0,
                "sale_rate_days": 0,
            }
        )
    candidates.sort(key=lambda item: as_int(item.get("stock")))
    if not candidates:
        return []

    active = call_with_retry(client, "wb_list_campaigns", {"statuses": [9]})
    nm_ids = {as_int(item.get("nmId")) for item in candidates}
    nm_to_campaigns: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for campaign in campaign_rows(active):
        campaign_id = as_int(campaign.get("id"))
        name = str(mapping(campaign.get("settings")).get("name", "?"))
        status = as_int(campaign.get("status"))
        for setting in rows(campaign.get("nm_settings")):
            nm_id = as_int(setting.get("nm_id"))
            if nm_id in nm_ids:
                nm_to_campaigns[nm_id].append(
                    {
                        "advertId": campaign_id,
                        "name": name,
                        "status": status,
                    }
                )

    week_spend = _weekly_spend(db_path)
    filtered: list[dict[str, object]] = []
    for candidate in candidates:
        nm_id = as_int(candidate.get("nmId"))
        adverts: list[dict[str, object]] = []
        for advert in nm_to_campaigns.get(nm_id, []):
            campaign_id = as_int(advert.get("advertId"))
            spend = week_spend.get(campaign_id, 0)
            if as_int(advert.get("status")) == 9 and spend >= MIN_WEEK_SPEND:
                adverts.append({**advert, "week_spend": round(spend)})
        if adverts:
            candidate["adverts"] = adverts
            filtered.append(candidate)
    return filtered


def format_report(
    candidates: list[dict[str, object]],
) -> str:
    lines = ["⚠️ **Кончаются + рекламируются** (остаток ≤50 шт, РК ≥500₽/нед):\n"]
    for candidate in candidates[:30]:
        advert_parts = []
        for advert in rows(candidate.get("adverts")):
            campaign_id = as_int(advert.get("advertId"))
            advert_parts.append(
                f"`{campaign_id}` ({as_int(advert.get('week_spend')):,}₽/нед)"
            )
        lines.append(
            f"📦 **{candidate.get('article', '?')}** — {candidate.get('stock', 0)} шт "
            f"({candidate.get('sale_rate_days', 0)} дн, "
            f"{candidate.get('avg_orders_day', 0)} зак/д) → РК "
            f"{', '.join(advert_parts)}"
        )
    if len(candidates) > 30:
        lines.append(f"...и ещё {len(candidates) - 30}")
    lines.append(
        "\n🔒 Скрипт только читает данные. Для паузы покажи кандидатов "
        "пользователю, затем выполни plan → apply → read-back в одной "
        "живой MCP-сессии Hermes."
    )
    return "\n".join(lines)


def main() -> int:
    if sys.argv[1:]:
        print(
            "Этот скрипт только читает данные; пауза выполняется в живой "
            "MCP-сессии Hermes после подтверждения.",
            file=sys.stderr,
        )
        return 2
    db_path = Path(os.getenv("WB_ADV_DB", str(DEFAULT_DB)))
    try:
        with WBMCPClient() as client:
            print("Pulling stock data...", file=sys.stderr)
            candidates = collect_candidates(client, db_path=db_path)
            print(
                f"After active-ads filter (>= {MIN_WEEK_SPEND}₽/week): "
                f"{len(candidates)}",
                file=sys.stderr,
            )
            if not candidates:
                return 0
        print(format_report(candidates))
        return 0
    except MCPClientError as error:
        print(f"WB MCP error: {error}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
