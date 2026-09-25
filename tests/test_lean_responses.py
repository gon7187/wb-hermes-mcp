import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from test_server import RecordingGateway

from wb_mcp import server


class ShapedGateway(RecordingGateway):
    """Returns realistic WB shapes for the reads the lean views collapse."""

    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("read", operation, payload))
        if operation == "search_cluster_stats":
            day = {"views": 100, "clicks": 10, "atbs": 1, "orders": 0, "spend": 50.5}
            return {
                "items": [
                    {
                        "advertId": 1,
                        "nmId": 2,
                        "dailyStats": [
                            {"date": "2026-09-18", "stat": {**day, "normQuery": "a"}},
                            {"date": "2026-09-19", "stat": {**day, "normQuery": "a"}},
                            {"date": "2026-09-19", "stat": {**day, "normQuery": "b"}},
                        ],
                    }
                ]
            }
        if operation == "campaign_spend_history":
            row = {"advertId": 1, "campName": "x", "updSum": 100}
            return {
                "data": [
                    {**row, "updTime": "2026-09-18T01:00:00"},
                    {**row, "updTime": "2026-09-19T01:00:00"},
                ]
            }
        if operation == "list_campaigns":
            return {
                "adverts": [
                    {
                        "id": 1,
                        "status": 9,
                        "bid_type": "manual",
                        "currency": "RUB",
                        "restrictions": {"can_change_nms": True},
                        "settings": {"name": "x", "payment_type": "cpm"},
                        "nm_settings": [{"nm_id": 2, "subject": {"id": 3}}],
                        "timestamps": {"created": "2026-09-01T10:00:00+03:00"},
                    }
                ]
            }
        if operation == "minus_phrases":
            return {"items": [{"advert_id": 1, "nm_id": 2, "norm_queries": ["old"]}]}
        return super().read(operation, payload)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _call(g: RecordingGateway, name: str, arguments: dict[str, object]):
    s = server.create_server(token="test-token", gateway=g)
    async with create_connected_server_and_client_session(s) as client:
        return await client.call_tool(name, arguments)


PERIOD = {"date_from": "2026-09-18", "date_to": "2026-09-19"}


@pytest.mark.anyio
async def test_cluster_stats_summary_totals_each_cluster_and_text_is_compact() -> None:
    items = [{"campaign_id": 1, "nm_id": 2}]
    payload = {**PERIOD, "items": items}
    result = await _call(
        ShapedGateway(), "wb_get_search_cluster_stats", {"payload": payload}
    )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "\n" not in text
    clusters = json.loads(text)["items"][0]["clusters"]
    assert [c["normQuery"] for c in clusters] == ["a", "b"]
    assert clusters[0]["clicks"] == 20
    assert clusters[0]["spend"] == 101.0


@pytest.mark.anyio
async def test_spend_history_summary_groups_by_day_and_campaign() -> None:
    result = await _call(
        ShapedGateway(), "wb_get_campaign_spend_history", {"payload": PERIOD}
    )

    body = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert body["total"] == 200
    assert [d["date"] for d in body["by_day"]] == ["2026-09-18", "2026-09-19"]
    assert body["by_campaign"] == [{"advertId": 1, "campName": "x", "sum": 200}]


@pytest.mark.anyio
async def test_minus_phrases_add_mode_keeps_existing_phrases() -> None:
    g = ShapedGateway()
    payload = {"campaign_id": 1, "nm_id": 2, "phrases": ["new", "old"], "mode": "add"}
    s = server.create_server(token="test-token", gateway=g)
    async with create_connected_server_and_client_session(s) as client:
        planned = await client.call_tool(
            "wb_plan_update_minus_phrases", {"payload": payload}
        )
        confirmation = json.loads(planned.content[0].text)["confirmation_id"]  # type: ignore[union-attr]
        await client.call_tool("wb_apply_changes", {"confirmation_ids": [confirmation]})

    writes = [c for c in g.calls if c[0] == "write"]
    assert writes == [
        (
            "write",
            "set_minus_phrases",
            {"campaign_id": 1, "nm_id": 2, "phrases": ["old", "new"]},
        )
    ]


@pytest.mark.anyio
async def test_apply_changes_reports_each_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    g = RecordingGateway()
    s = server.create_server(token="test-token", gateway=g)
    pause = {"action": "pause", "campaign_id": 7}
    async with create_connected_server_and_client_session(s) as client:
        planned = await client.call_tool("wb_plan_update_campaign", {"payload": pause})
        confirmation = json.loads(planned.content[0].text)["confirmation_id"]  # type: ignore[union-attr]
        result = await client.call_tool(
            "wb_apply_changes", {"confirmation_ids": [confirmation, "unknown-id"]}
        )

    body = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert body["applied"] == 1
    assert body["failed"] == 1
    assert body["results"][0]["status"] == "applied"


@pytest.mark.anyio
async def test_list_campaigns_summary_drops_noise_fields() -> None:
    result = await _call(ShapedGateway(), "wb_list_campaigns", {"payload": {}})

    advert = json.loads(result.content[0].text)["adverts"][0]  # type: ignore[union-attr]
    assert "currency" not in advert and "restrictions" not in advert
    assert advert["nms"] == [{"nm_id": 2, "bids_kopecks": None}]
    assert advert["created"] == "2026-09-01"
