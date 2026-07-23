#!/usr/bin/env python3
"""Read-only WB campaign and budget summary for Hermes cron."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable

try:
    from .wb_common import (
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
    )
    from .wb_mcp_client import MCPClientError, WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
    )
    from wb_mcp_client import MCPClientError, WBMCPClient  # type: ignore[no-redef]

BUDGET_THRESHOLD = 1000


def collect_monitor(
    client: MCPCaller,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    campaigns: list[dict[str, object]] = []
    partial = False
    for status in (9, 11):
        try:
            result = call_with_retry(
                client,
                "wb_list_campaigns",
                {"statuses": [status]},
                sleep=sleep,
            )
        except MCPClientError:
            partial = True
            continue
        campaigns.extend(campaign_rows(result))
        sleep(0.5)

    active = sum(1 for campaign in campaigns if campaign.get("status") == 9)
    paused = sum(1 for campaign in campaigns if campaign.get("status") == 11)
    total_budget = 0
    low_budget: list[dict[str, object]] = []
    for index, campaign in enumerate(campaigns):
        campaign_id = as_int(campaign.get("id"))
        try:
            budget_result = call_with_retry(
                client,
                "wb_get_campaign_budget",
                {"campaign_id": campaign_id},
                sleep=sleep,
            )
        except MCPClientError:
            partial = True
            continue
        budget = as_int(budget_result.get("total"))
        total_budget += budget
        if budget < BUDGET_THRESHOLD:
            low_budget.append(
                {
                    "id": campaign_id,
                    "name": str(mapping(campaign.get("settings")).get("name", "?")),
                    "status": as_int(campaign.get("status")),
                    "budget": budget,
                }
            )
        if (index + 1) % 4 == 0:
            sleep(1)
    low_budget.sort(key=lambda item: as_int(item.get("budget")))
    result: dict[str, object] = {
        "active": active,
        "paused": paused,
        "total_budget": total_budget,
        "low_budget": low_budget,
    }
    if partial:
        result["partial"] = True
    return result


def main() -> int:
    try:
        with WBMCPClient() as client:
            result = collect_monitor(client)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except MCPClientError as error:
        print(f"WB MCP error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
