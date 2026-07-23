#!/usr/bin/env python3
"""Print today's live WB campaign totals as the established JSON contract."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date

try:
    from .wb_common import (
        MCPCaller,
        as_float,
        as_int,
        call_with_retry,
        campaign_rows,
        data_rows,
        mapping,
    )
    from .wb_mcp_client import WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_float,
        as_int,
        call_with_retry,
        campaign_rows,
        data_rows,
        mapping,
    )
    from wb_mcp_client import WBMCPClient  # type: ignore[no-redef]


def build_summary(
    client: MCPCaller,
    *,
    target_date: date | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    selected_date = target_date or date.today()
    live = call_with_retry(
        client,
        "wb_list_campaigns",
        {"statuses": [4, 9, 11]},
        sleep=sleep,
    )
    campaigns = campaign_rows(live)
    campaign_ids = [as_int(item.get("id")) for item in campaigns if item.get("id")]
    names = {
        as_int(item.get("id")): str(mapping(item.get("settings")).get("name", ""))
        for item in campaigns
    }

    stats: list[dict[str, object]] = []
    batches = [
        campaign_ids[index : index + 50] for index in range(0, len(campaign_ids), 50)
    ]
    for index, batch in enumerate(batches):
        result = call_with_retry(
            client,
            "wb_get_campaign_stats",
            {
                "campaign_ids": batch,
                "date_from": selected_date.isoformat(),
                "date_to": selected_date.isoformat(),
            },
            sleep=sleep,
        )
        stats.extend(data_rows(result))
        if index < len(batches) - 1:
            sleep(65)

    spend = sum(as_float(item.get("sum")) for item in stats)
    orders = sum(as_int(item.get("orders")) for item in stats)
    revenue = sum(as_float(item.get("sum_price")) for item in stats)
    top = sorted(
        [
            [
                campaign_id,
                names.get(campaign_id, ""),
                as_float(item.get("sum")),
                as_int(item.get("orders")),
                as_float(item.get("sum_price")),
            ]
            for item in stats
            if (campaign_id := as_int(item.get("advertId")))
        ],
        key=lambda item: float(item[2]),
        reverse=True,
    )[:10]
    return {
        "date": selected_date.isoformat(),
        "campaigns": len(campaign_ids),
        "spend": round(spend),
        "orders": orders,
        "revenue": round(revenue),
        "drr": round(spend / revenue * 100, 1) if revenue else None,
        "top": top,
    }


def main() -> int:
    with WBMCPClient() as client:
        summary = build_summary(client)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
