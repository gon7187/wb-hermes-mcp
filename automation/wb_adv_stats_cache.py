#!/usr/bin/env python3
"""Cache recent WB campaign statistics through the explicit `wb` MCP."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

try:
    from .wb_common import (
        MCPCaller,
        as_float,
        as_int,
        call_with_retry,
        campaign_rows,
        data_rows,
        mapping,
        rows,
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
        rows,
    )
    from wb_mcp_client import WBMCPClient  # type: ignore[no-redef]

DEFAULT_DB = Path("/root/.hermes/data/wb_adv_stats.db")


@dataclass(frozen=True)
class CacheResult:
    rows: int
    campaigns: int
    begin: date
    end: date


def _campaign_inventory(
    client: MCPCaller,
) -> tuple[list[int], list[tuple[int, int, int]], dict[int, str]]:
    grouped = call_with_retry(client, "wb_get_campaign_counts")
    campaign_ids: list[int] = []
    status_rows: list[tuple[int, int, int]] = []
    for group in rows(grouped.get("adverts")):
        status = as_int(group.get("status"))
        campaign_type = as_int(group.get("type"))
        for advert in rows(group.get("advert_list")):
            campaign_id = as_int(advert.get("advertId"))
            if not campaign_id:
                continue
            status_rows.append((campaign_id, status, campaign_type))
            if status in {4, 9, 11}:
                campaign_ids.append(campaign_id)

    live = call_with_retry(
        client,
        "wb_list_campaigns",
        {"statuses": [4, 9, 11]},
    )
    names = {
        as_int(campaign.get("id")): str(
            mapping(campaign.get("settings")).get("name", "")
        )
        for campaign in campaign_rows(live)
    }
    return sorted(set(campaign_ids)), status_rows, names


def refresh_cache(
    client: MCPCaller,
    *,
    db_path: str | Path = DEFAULT_DB,
    window: int = 3,
    today: date | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CacheResult:
    if window < 1:
        raise ValueError("days must be at least one")
    target_today = today or date.today()
    campaign_ids, statuses, names = _campaign_inventory(client)
    if not campaign_ids:
        raise RuntimeError("no campaigns returned by WB")

    end = target_today - timedelta(days=1)
    begin = end - timedelta(days=window - 1)
    database = Path(db_path)
    database.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adv_daily(
                advert_id INTEGER,
                date TEXT,
                views INTEGER,
                clicks INTEGER,
                spend REAL,
                orders INTEGER,
                revenue REAL,
                atbs INTEGER,
                cpm REAL,
                name TEXT,
                fetched_at TEXT,
                PRIMARY KEY(advert_id, date)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adv_status(
                advert_id INTEGER,
                snap_date TEXT,
                status INTEGER,
                type INTEGER,
                PRIMARY KEY(advert_id, snap_date)
            )
            """
        )
        connection.executemany(
            "INSERT OR REPLACE INTO adv_status VALUES(?,?,?,?)",
            [
                (campaign_id, target_today.isoformat(), status, campaign_type)
                for campaign_id, status, campaign_type in statuses
            ],
        )

        stored_rows = 0
        batches = [
            campaign_ids[index : index + 50]
            for index in range(0, len(campaign_ids), 50)
        ]
        for index, batch in enumerate(batches):
            result = call_with_retry(
                client,
                "wb_get_campaign_stats",
                {
                    "campaign_ids": batch,
                    "date_from": begin.isoformat(),
                    "date_to": end.isoformat(),
                },
                sleep=sleep,
            )
            for campaign in data_rows(result):
                campaign_id = as_int(campaign.get("advertId"))
                for day in rows(campaign.get("days")):
                    spend = as_float(day.get("sum"))
                    views = as_int(day.get("views"))
                    cpm = as_float(day.get("cpm"))
                    if cpm == 0 and views > 0:
                        cpm = spend / views * 1000
                    connection.execute(
                        "INSERT OR REPLACE INTO adv_daily VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            campaign_id,
                            str(day.get("date", ""))[:10],
                            views,
                            as_int(day.get("clicks")),
                            spend,
                            as_int(day.get("orders")),
                            as_float(day.get("sum_price")),
                            as_int(day.get("atbs")),
                            cpm,
                            names.get(campaign_id, ""),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    stored_rows += 1
            if index < len(batches) - 1:
                sleep(65)

    return CacheResult(stored_rows, len(campaign_ids), begin, end)


def main() -> int:
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    db_path = Path(os.getenv("WB_ADV_DB", str(DEFAULT_DB)))
    try:
        with WBMCPClient() as client:
            result = refresh_cache(client, db_path=db_path, window=window)
        if sys.stdout.isatty():
            print(
                f"OK: {result.rows} day-rows | {result.campaigns} campaigns | "
                f"{result.begin}..{result.end}"
            )
        return 0
    except Exception as error:
        print(f"wb_adv_stats_cache FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
