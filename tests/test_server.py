import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from wb_mcp import server
from wb_mcp.gateway import WBError


class RecordingGateway:
    """In-memory SDK boundary used to observe public MCP behaviour."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("read", operation, payload))
        return {"operation": operation, "payload": payload}

    def write(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("write", operation, payload))
        return {"operation": operation, "payload": payload}


class FailingGateway(RecordingGateway):
    def write(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("write", operation, payload))
        raise WBError(
            operation=operation,
            kind="request_rejected",
            message="Wildberries rejected this request; review the payload.",
            retryable=False,
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_server_has_wb_name() -> None:
    assert server.create_server(token="test-token").name == "wb_mcp"


def test_main_uses_stdio_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingServer:
        transport: str | None = None

        def run(self, *, transport: str) -> None:
            self.transport = transport

    recording_server = RecordingServer()
    monkeypatch.setattr(server, "create_server", lambda: recording_server)

    server.main()

    assert recording_server.transport == "stdio"


@pytest.mark.anyio
async def test_server_exposes_catalog_inventory_order_and_supply_tools() -> None:
    gateway = RecordingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    expected = {
        "wb_list_cards",
        "wb_get_card_schema",
        "wb_list_card_errors",
        "wb_list_tags",
        "wb_list_prices",
        "wb_get_stocks",
        "wb_list_warehouses",
        "wb_list_orders",
        "wb_list_new_orders",
        "wb_get_order_statuses",
        "wb_get_order_stickers",
        "wb_list_supplies",
        "wb_get_supply",
        "wb_get_supply_barcode",
        "wb_plan_update_cards",
        "wb_plan_save_media",
        "wb_plan_set_prices",
        "wb_plan_set_stocks",
        "wb_plan_manage_warehouse",
        "wb_plan_cancel_order",
        "wb_plan_create_supply",
        "wb_plan_update_supply",
        "wb_apply_change",
    }

    assert expected <= tools.keys()
    assert tools["wb_list_cards"].annotations is not None
    assert tools["wb_plan_set_prices"].annotations is not None
    assert tools["wb_apply_change"].annotations is not None
    assert tools["wb_list_cards"].annotations.readOnlyHint is True
    assert tools["wb_plan_set_prices"].annotations.readOnlyHint is False
    assert tools["wb_apply_change"].annotations.readOnlyHint is False
    assert tools["wb_apply_change"].annotations.destructiveHint is True
    assert tools["wb_get_order_statuses"].annotations is not None
    assert tools["wb_get_order_statuses"].annotations.readOnlyHint is True
    assert "wb_get_order_details" not in tools
    assert "wb_plan_update_order_status" not in tools
    assert tools["wb_list_orders"].inputSchema["additionalProperties"] is False


@pytest.mark.anyio
async def test_plan_does_not_call_the_sdk_until_applied_once() -> None:
    gateway = RecordingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        plan = await client.call_tool("wb_plan_set_prices", {"payload": {"items": []}})

        assert gateway.calls == []
        assert plan.structuredContent is not None
        confirmation_id = plan.structuredContent["confirmation_id"]
        assert isinstance(confirmation_id, str)
        assert plan.structuredContent["summary"] == {
            "operation": "set_prices",
            "targets": [],
            "payload": {"items": []},
        }

        applied = await client.call_tool(
            "wb_apply_change", {"confirmation_id": confirmation_id}
        )

    assert gateway.calls == [("write", "set_prices", {"items": []})]
    assert applied.structuredContent is not None
    assert applied.structuredContent["status"] == "applied"


@pytest.mark.anyio
async def test_read_tool_routes_its_validated_payload_to_a_named_gateway_operation() -> (
    None
):
    gateway = RecordingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "wb_list_orders",
            {"payload": {"limit": 10, "next": 0, "date_from": 1_700_000_000}},
        )

    assert gateway.calls == [
        (
            "read",
            "list_orders",
            {"limit": 10, "next": 0, "date_from": 1_700_000_000},
        )
    ]
    assert result.structuredContent == {
        "operation": "list_orders",
        "payload": {"limit": 10, "next": 0, "date_from": 1_700_000_000},
    }


@pytest.mark.anyio
async def test_order_statuses_are_read_only_and_use_the_named_read_operation() -> None:
    gateway = RecordingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "wb_get_order_statuses", {"payload": {"order_ids": [12345678]}}
        )

    assert gateway.calls == [("read", "get_order_statuses", {"order_ids": [12345678]})]
    assert result.structuredContent == {
        "operation": "get_order_statuses",
        "payload": {"order_ids": [12345678]},
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments",
    [
        {"payload": {"limit": 1, "next": 0}, "secret": "SECRET_MARKER"},
        {"payload": {"limit": 1, "next": 0, "secret": "SECRET_MARKER"}},
        {"payload": {"limit": "SECRET_MARKER", "next": 0}},
    ],
)
async def test_invalid_tool_input_is_a_structured_error_without_echoing_values(
    arguments: dict[str, object],
) -> None:
    wb_server = server.create_server(token="test-token", gateway=RecordingGateway())

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        result = await client.call_tool("wb_list_orders", arguments)

    assert result.isError is True
    assert result.structuredContent == {
        "ok": False,
        "error": {
            "kind": "validation_error",
            "message": "Некорректные параметры инструмента. Проверьте структуру и обязательные поля.",
            "retryable": False,
        },
    }
    assert "SECRET_MARKER" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.anyio
async def test_failed_apply_consumes_confirmation_and_never_retries_write() -> None:
    gateway = FailingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        plan = await client.call_tool("wb_plan_set_prices", {"payload": {"items": []}})
        assert plan.structuredContent is not None
        confirmation_id = plan.structuredContent["confirmation_id"]
        assert isinstance(confirmation_id, str)

        failed = await client.call_tool(
            "wb_apply_change", {"confirmation_id": confirmation_id}
        )
        replay = await client.call_tool(
            "wb_apply_change", {"confirmation_id": confirmation_id}
        )

    assert failed.structuredContent is not None
    assert failed.structuredContent["ok"] is False
    assert replay.structuredContent is not None
    assert replay.structuredContent["ok"] is False
    assert gateway.calls == [("write", "set_prices", {"items": []})]


@pytest.mark.anyio
async def test_successful_apply_is_single_use_and_never_replays_the_write() -> None:
    gateway = RecordingGateway()
    wb_server = server.create_server(token="test-token", gateway=gateway)

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        plan = await client.call_tool("wb_plan_set_prices", {"payload": {"items": []}})
        assert plan.structuredContent is not None
        confirmation_id = plan.structuredContent["confirmation_id"]
        assert isinstance(confirmation_id, str)

        applied = await client.call_tool(
            "wb_apply_change", {"confirmation_id": confirmation_id}
        )
        replay = await client.call_tool(
            "wb_apply_change", {"confirmation_id": confirmation_id}
        )

    assert applied.structuredContent is not None
    assert applied.structuredContent["ok"] is True
    assert replay.structuredContent is not None
    assert replay.structuredContent["ok"] is False
    assert gateway.calls == [("write", "set_prices", {"items": []})]


@pytest.mark.anyio
async def test_plan_summary_redacts_secret_like_values() -> None:
    wb_server = server.create_server(token="test-token", gateway=RecordingGateway())

    async with create_connected_server_and_client_session(
        wb_server, raise_exceptions=True
    ) as client:
        plan = await client.call_tool(
            "wb_plan_create_supply", {"payload": {"name": "SECRET_MARKER"}}
        )

    assert plan.structuredContent is not None
    assert plan.structuredContent["summary"] == {
        "operation": "create_supply",
        "targets": [],
        "payload": {"name": "[redacted]"},
    }
    assert "SECRET_MARKER" not in json.dumps(plan.model_dump(mode="json"))
