from __future__ import annotations

import sqlite3
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from automation import (
    wb_common,
    wb_adv_stats_cache,
    wb_adv_today_live,
    wb_budget_dashboard,
    wb_camp_health,
    wb_camp_monitor,
    wb_create_camp,
    wb_low_stock_monitor,
    wb_new_stock_detector,
)
from automation.wb_mcp_client import MCPToolError


class FakeClient:
    def __init__(self, responses: Mapping[str, list[dict[str, object]]]) -> None:
        self.responses = {name: list(items) for name, items in responses.items()}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((name, dict(arguments or {})))
        return self.responses[name].pop(0)


class RateLimitedStatsClient(FakeClient):
    def __init__(self, responses: Mapping[str, list[dict[str, object]]]) -> None:
        super().__init__(responses)
        self.stats_attempts = 0

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if name == "wb_get_campaign_stats":
            self.calls.append((name, dict(arguments or {})))
            self.stats_attempts += 1
            if self.stats_attempts == 1:
                raise MCPToolError(kind="rate_limited", retryable=True)
            return self.responses[name].pop(0)
        return super().call_tool(name, arguments)


class RetryableClient(FakeClient):
    def __init__(
        self,
        *,
        tool: str,
        kind: str,
        response: dict[str, object],
    ) -> None:
        super().__init__({tool: [response]})
        self.tool = tool
        self.kind = kind
        self.attempts = 0

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((name, dict(arguments or {})))
        self.attempts += 1
        if self.attempts == 1:
            raise MCPToolError(kind=self.kind, retryable=True)
        return self.responses[name].pop(0)


def campaign_fixture() -> dict[str, object]:
    return {
        "adverts": [
            {
                "id": 101,
                "status": 9,
                "settings": {"name": "Campaign A"},
                "nm_settings": [{"nm_id": 501}],
            }
        ]
    }


def test_stats_cache_preserves_the_existing_sqlite_contract(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "wb_get_campaign_counts": [
                {
                    "adverts": [
                        {
                            "status": 9,
                            "type": 8,
                            "advert_list": [{"advertId": 101}],
                        }
                    ]
                }
            ],
            "wb_list_campaigns": [campaign_fixture()],
            "wb_get_campaign_stats": [
                {
                    "data": [
                        {
                            "advertId": 101,
                            "days": [
                                {
                                    "date": "2026-07-22",
                                    "views": 1000,
                                    "clicks": 40,
                                    "sum": 250,
                                    "orders": 3,
                                    "sum_price": 5000,
                                    "atbs": 5,
                                }
                            ],
                        }
                    ]
                }
            ],
        }
    )
    db_path = tmp_path / "stats.db"

    result = wb_adv_stats_cache.refresh_cache(
        client,
        db_path=db_path,
        window=1,
        today=date(2026, 7, 23),
        sleep=lambda _: None,
    )

    with sqlite3.connect(db_path) as connection:
        daily = connection.execute(
            "SELECT advert_id,date,views,clicks,spend,orders,revenue,atbs,cpm,name "
            "FROM adv_daily"
        ).fetchone()
        status = connection.execute(
            "SELECT advert_id,snap_date,status,type FROM adv_status"
        ).fetchone()
    assert result.rows == 1
    assert daily == (
        101,
        "2026-07-22",
        1000,
        40,
        250.0,
        3,
        5000.0,
        5,
        250.0,
        "Campaign A",
    )
    assert status == (101, "2026-07-23", 9, 8)


def test_today_summary_keeps_the_legacy_json_shape() -> None:
    client = FakeClient(
        {
            "wb_list_campaigns": [campaign_fixture()],
            "wb_get_campaign_stats": [
                {
                    "data": [
                        {
                            "advertId": 101,
                            "sum": 250.4,
                            "orders": 3,
                            "sum_price": 5000.2,
                        }
                    ]
                }
            ],
        }
    )

    summary = wb_adv_today_live.build_summary(
        client,
        target_date=date(2026, 7, 23),
        sleep=lambda _: None,
    )

    assert summary == {
        "date": "2026-07-23",
        "campaigns": 1,
        "spend": 250,
        "orders": 3,
        "revenue": 5000,
        "drr": 5.0,
        "top": [[101, "Campaign A", 250.4, 3, 5000.2]],
    }


def test_today_summary_retries_a_retryable_rate_limit() -> None:
    client = RateLimitedStatsClient(
        {
            "wb_list_campaigns": [campaign_fixture()],
            "wb_get_campaign_stats": [{"data": []}],
        }
    )
    sleeps: list[float] = []

    wb_adv_today_live.build_summary(
        client,
        target_date=date(2026, 7, 23),
        sleep=sleeps.append,
    )

    assert client.stats_attempts == 2
    assert sleeps == [65]


def test_today_summary_reports_rate_limit_wait(capsys) -> None:
    client = FakeClient(
        {
            "wb_list_campaigns": [
                {
                    "adverts": [
                        {"id": campaign_id, "settings": {"name": str(campaign_id)}}
                        for campaign_id in range(1, 52)
                    ]
                }
            ],
            "wb_get_campaign_stats": [{"data": []}, {"data": []}],
        }
    )

    wb_adv_today_live.build_summary(
        client,
        target_date=date(2026, 7, 23),
        sleep=lambda _: None,
    )

    assert capsys.readouterr().err == (
        "WB stats: batch 1/2 complete; waiting 65s for API rate limit\n"
    )


def test_stats_cache_retries_a_retryable_rate_limit(tmp_path: Path) -> None:
    client = RateLimitedStatsClient(
        {
            "wb_get_campaign_counts": [
                {
                    "adverts": [
                        {
                            "status": 9,
                            "type": 8,
                            "advert_list": [{"advertId": 101}],
                        }
                    ]
                }
            ],
            "wb_list_campaigns": [campaign_fixture()],
            "wb_get_campaign_stats": [{"data": []}],
        }
    )
    sleeps: list[float] = []

    wb_adv_stats_cache.refresh_cache(
        client,
        db_path=tmp_path / "stats.db",
        window=1,
        today=date(2026, 7, 23),
        sleep=sleeps.append,
    )

    assert client.stats_attempts == 2
    assert sleeps == [65]


def test_campaign_health_retries_a_retryable_rate_limit() -> None:
    client = RateLimitedStatsClient(
        {
            "wb_list_campaigns": [campaign_fixture(), {"adverts": []}],
            "wb_get_campaign_spend_history": [{"data": []}],
            "wb_get_campaign_budget": [{"total": 500}],
            "wb_get_campaign_stats": [
                {
                    "data": [
                        {
                            "advertId": 101,
                            "sum": 600,
                            "sum_price": 6000,
                            "atbs": 4,
                            "clicks": 20,
                        }
                    ]
                }
            ],
        }
    )
    sleeps: list[float] = []

    result = wb_camp_health.collect_health(
        client,
        today=date(2026, 7, 23),
        sleep=sleeps.append,
    )

    assert client.stats_attempts == 2
    assert result.junk == 0
    assert len(result.notify) == 1
    assert sleeps[-1] == 65


def test_shared_read_retry_handles_a_temporary_service_failure() -> None:
    client = RetryableClient(
        tool="wb_get_balance",
        kind="service_unavailable",
        response={"balance": 100},
    )
    sleeps: list[float] = []

    result = wb_common.call_with_retry(
        client,
        "wb_get_balance",
        sleep=sleeps.append,
    )

    assert result == {"balance": 100}
    assert client.attempts == 2
    assert sleeps == [15]


def test_shared_read_retry_restarts_after_a_client_transport_failure() -> None:
    class RestartableClient:
        attempts = 0
        restarts = 0

        def call_tool(
            self,
            name: str,
            arguments: Mapping[str, object] | None = None,
        ) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                raise wb_common.MCPClientError("safe transport failure")
            return {"ok": True}

        def restart(self) -> None:
            self.restarts += 1

    client = RestartableClient()
    sleeps: list[float] = []

    result = wb_common.call_with_retry(
        client,
        "wb_get_balance",
        sleep=sleeps.append,
    )

    assert result == {"ok": True}
    assert client.restarts == 1
    assert sleeps == [5]


def test_budget_dashboard_uses_sales_without_returns() -> None:
    client = FakeClient(
        {
            "wb_list_sales": [
                {
                    "data": [
                        {
                            "date": "2026-07-13T12:00:00",
                            "saleID": "S1",
                            "priceWithDisc": 1000,
                        },
                        {
                            "date": "2026-07-14T12:00:00",
                            "saleID": "R1",
                            "priceWithDisc": 400,
                        },
                        {
                            "date": "2026-07-22T12:00:00",
                            "saleID": "S2",
                            "priceWithDisc": 900,
                        },
                    ]
                }
            ]
        }
    )

    assert (
        wb_budget_dashboard.fetch_gmv_week(
            client,
            date(2026, 7, 13),
            date(2026, 7, 19),
        )
        == 1000
    )


def test_campaign_monitor_keeps_the_legacy_json_shape() -> None:
    client = FakeClient(
        {
            "wb_list_campaigns": [
                campaign_fixture(),
                {
                    "adverts": [
                        {
                            "id": 102,
                            "status": 11,
                            "settings": {"name": "Campaign B"},
                        }
                    ]
                },
            ],
            "wb_get_campaign_budget": [{"total": 500}, {"total": 1500}],
        }
    )

    result = wb_camp_monitor.collect_monitor(client, sleep=lambda _: None)

    assert result == {
        "active": 1,
        "paused": 1,
        "total_budget": 2000,
        "low_budget": [{"id": 101, "name": "Campaign A", "status": 9, "budget": 500}],
    }


def test_campaign_monitor_marks_partial_data_when_one_read_fails() -> None:
    class PartialClient:
        calls = 0

        def call_tool(
            self,
            name: str,
            arguments: Mapping[str, object] | None = None,
        ) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise MCPToolError(kind="request_rejected", retryable=False)
            return {"adverts": []}

    result = wb_camp_monitor.collect_monitor(
        PartialClient(),
        sleep=lambda _: None,
    )

    assert result == {
        "active": 0,
        "paused": 0,
        "total_budget": 0,
        "low_budget": [],
        "partial": True,
    }


def test_new_stock_detector_preserves_state_and_transition_contract() -> None:
    client = FakeClient(
        {
            "wb_get_wb_warehouse_stocks": [
                {
                    "data": {
                        "items": [
                            {
                                "nmId": 501,
                                "warehouseName": "Коледино",
                                "quantity": 25,
                            }
                        ]
                    }
                }
            ]
        }
    )

    current = wb_new_stock_detector.collect_current_stocks(client)
    new_items = wb_new_stock_detector.find_new_items(
        current,
        {"501": {"total": 5}},
    )

    assert current == {
        501: {
            "total": 25,
            "warehouses": {"Коледино": 25},
            "type": ["FBO"],
        }
    }
    assert new_items == [{"nmId": 501, "total": 25, "warehouses": {"Коледино": 25}}]


def test_low_stock_candidates_are_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "stats.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE adv_daily(advert_id INTEGER, date TEXT, spend REAL)"
        )
        connection.execute("INSERT INTO adv_daily VALUES(101, date('now'), 700)")
    client = FakeClient(
        {
            "wb_get_stock_products": [
                {
                    "data": {
                        "items": [
                            {
                                "nmID": 501,
                                "name": "Product",
                                "vendorCode": "SKU",
                                "metrics": {"stockCount": 10},
                            }
                        ]
                    }
                }
            ],
            "wb_list_campaigns": [campaign_fixture()],
        }
    )

    candidates = wb_low_stock_monitor.collect_candidates(
        client,
        db_path=db_path,
        today=date.today(),
    )
    assert candidates[0]["adverts"] == [
        {
            "advertId": 101,
            "name": "Campaign A",
            "status": 9,
            "week_spend": 700,
        }
    ]
    assert all(not name.startswith("wb_plan_") for name, _ in client.calls)


def test_campaign_creation_proposal_contains_no_ephemeral_confirmation() -> None:
    proposal = wb_create_camp.build_campaign_proposal(
        nm_id=501,
        name="Product",
        article="SKU",
        today=date(2026, 7, 23),
    )

    assert proposal == {
        "action": "create",
        "name": "SKU_Product/23.07",
        "nm_ids": [501],
        "bid_type": "manual",
        "payment_type": "cpm",
        "placement_types": ["search", "recommendations"],
    }
    assert "confirmation_id" not in proposal


def test_standalone_write_flags_are_rejected_before_opening_mcp(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(sys, "argv", ["wb_camp_health.py", "--apply"])
    assert wb_camp_health.main() == 2
    assert "живой MCP-сессии" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["wb_low_stock_monitor.py", "--plan-pause"])
    assert wb_low_stock_monitor.main() == 2
    assert "живой MCP-сессии" in capsys.readouterr().err


def test_migrated_sources_do_not_reference_the_legacy_secret_store() -> None:
    scripts = Path("automation").glob("wb_*.py")
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in scripts)

    assert "cabinets.json" not in rendered
    assert "Authorization" not in rendered
    assert "wb_plan_" not in rendered
    assert "wb_apply_change" not in rendered
