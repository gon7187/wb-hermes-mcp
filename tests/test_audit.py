from datetime import date

import pytest

from wb_mcp.audit import _channel, audit, zone_verdict
from wb_mcp.gateway import WBError


@pytest.mark.parametrize(
    ("search", "rest", "expected"),
    [
        # Real 2026-09-18..24 cases the manual audit settled on.
        ((12045, 1, 20000), (40130, 58, 20000), "disable_search"),  # Brando: 49% vs 3%
        ((13860, 0, 30000), (32067, 23, 30000), "disable_search"),  # 0 search orders
        ((1676, 1, 28000), (7216, 1, 28000), "disable_recommendations"),  # 6% vs 26%
        ((19001, 10, 27000), (127498, 107, 27000), "keep_both"),  # 7% vs 4%
        ((5735, 3, 19000), (34467, 11, 19000), "keep_both"),  # 10% vs 17%
        ((1126, 0, 11771), (2562, 1, 11771), "both_weak"),  # 0 orders vs 22%
        ((214, 0, 18582), (1212, 1, 18582), "keep_both"),  # search spend too small
    ],
)
def test_zone_verdict_matches_manual_decisions(search, rest, expected) -> None:
    assert zone_verdict(_channel(*search), _channel(*rest)) == expected


class FakeWB:
    def __init__(self) -> None:
        self.rate_limited_once = False

    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        if operation == "list_campaigns":
            return {
                "adverts": [
                    {
                        "id": 1,
                        "status": 9,
                        "bid_type": "manual",
                        "nm_settings": [{"nm_id": 11}],
                        "settings": {
                            "name": "Шкаф",
                            "payment_type": "cpm",
                            "placements": {"search": True, "recommendations": True},
                        },
                        "timestamps": {"created": "2026-05-01T00:00:00+03:00"},
                    },
                    {
                        "id": 2,
                        "status": 9,
                        "bid_type": "unified",
                        "nm_settings": [{"nm_id": 22}],
                        "settings": {
                            "name": "Стол",
                            "payment_type": "cpm",
                            "placements": {"search": True, "recommendations": True},
                        },
                        "timestamps": {"created": "2026-09-22T00:00:00+03:00"},
                    },
                ]
            }
        if operation == "campaign_stats":
            if not self.rate_limited_once:
                self.rate_limited_once = True
                raise WBError(
                    operation="campaign_stats",
                    kind="rate_limited",
                    message="slow down",
                    retryable=True,
                )
            return {
                "data": [
                    {"advertId": 1, "sum": 10000, "sum_price": 200000, "orders": 10},
                    {"advertId": 2, "sum": 5000, "sum_price": 100000, "orders": 5},
                ]
            }
        if operation == "search_cluster_stats":
            day = {"spend": 3000, "orders": 0, "clicks": 90, "atbs": 4}
            return {
                "items": [
                    {
                        "advertId": 1,
                        "dailyStats": [
                            {"stat": {**day, "normQuery": "мебель"}},
                            {"stat": {**day, "normQuery": "шкаф", "spend": 900}},
                        ],
                    }
                ]
            }
        if operation == "minus_phrases":
            return {"items": [{"advert_id": 1, "nm_id": 11, "norm_queries": ["шкаф"]}]}
        raise AssertionError(operation)


def test_audit_suggests_placements_and_skips_minus_listed_clusters() -> None:
    waits: list[float] = []

    result = audit(
        FakeWB().read, date(2026, 9, 18), date(2026, 9, 24), sleep=waits.append
    )

    assert waits == [20.0]
    assert result["suggested_placements"] == {
        "campaigns": [{"campaign_id": 1, "search": False, "recommendations": True}]
    }
    candidates = result["cluster_candidates"]
    assert isinstance(candidates, list)
    assert [c["norm_query"] for c in candidates] == ["мебель"]
    skipped = result["skipped"]
    assert isinstance(skipped, list)
    assert skipped[0]["campaign_id"] == 2
    assert skipped[0]["new"] is True
