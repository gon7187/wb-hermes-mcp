from dataclasses import dataclass
from datetime import date
from inspect import signature

import pytest
from pydantic import BaseModel

from wb_mcp import gateway as gateway_module
from wb_mcp.gateway import OPERATIONS, WBError, WildberriesGateway


class SellerProfile(BaseModel):
    seller_id: int
    name: str


@dataclass
class SellerResponse:
    profile: SellerProfile
    labels: list[dict[str, object]]


def test_gateway_dispatches_a_read_to_registered_sdk_method_and_serializes_response() -> (
    None
):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class General:
        def get_v1_seller_info(self, *args: object, **kwargs: object) -> SellerResponse:
            calls.append((args, kwargs))
            return SellerResponse(
                profile=SellerProfile(seller_id=42, name="seller"),
                labels=[{"kind": "verified"}],
            )

    gateway = WildberriesGateway("test-token", clients={"general": General()})

    assert gateway.read("seller_profile", {}) == {
        "profile": {"seller_id": 42, "name": "seller"},
        "labels": [{"kind": "verified"}],
    }
    assert calls == [((), {})]


def test_gateway_rejects_seller_profile_transport_kwargs_before_sdk_call() -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class General:
        def get_v1_seller_info(
            self, *args: object, **kwargs: object
        ) -> dict[str, object]:
            calls.append((args, kwargs))
            return {"name": "seller"}

    gateway = WildberriesGateway("test-token", clients={"general": General()})

    transport_payloads: tuple[dict[str, object], ...] = (
        {"_headers": {"Authorization": "secret-token"}},
        {"_request_auth": {"HeaderApiKey": "secret-token"}},
    )
    for payload in transport_payloads:
        with pytest.raises(WBError) as caught:
            gateway.read("seller_profile", payload)

        assert caught.value.kind == "invalid_payload"
        assert "secret-token" not in caught.value.message

    assert calls == []


def test_gateway_adapts_price_items_to_the_registered_sdk_request_model() -> None:
    received: list[object] = []

    class Items:
        def api_v2_upload_task_post(
            self, api_v2_upload_task_post_request: object
        ) -> dict[str, int]:
            received.append(api_v2_upload_task_post_request)
            return {"task_id": 7}

    gateway = WildberriesGateway("test-token", clients={"items": Items()})

    assert gateway.write(
        "set_prices",
        {"items": [{"nmID": 100, "price": 999, "discount": 10}]},
    ) == {"task_id": 7}
    assert len(received) == 1
    assert getattr(received[0], "model_dump")(by_alias=True) == {
        "data": [{"nmID": 100, "price": 999, "discount": 10}]
    }


def test_gateway_rejects_unknown_operations_without_echoing_input_or_token() -> None:
    token = "secret-token"
    gateway = WildberriesGateway(token, clients={})

    with pytest.raises(WBError) as caught:
        gateway.read("not-a-real-operation", {})

    error = caught.value
    assert error.operation == "unknown"
    assert error.kind == "unknown_operation"
    assert error.retryable is False
    assert "not-a-real-operation" not in error.message
    assert token not in error.message


def test_gateway_rejects_a_mode_mismatch_before_calling_the_sdk() -> None:
    class General:
        def get_v1_seller_info(self) -> dict[str, object]:
            raise AssertionError("a write must not call this read operation")

    gateway = WildberriesGateway("test-token", clients={"general": General()})

    with pytest.raises(WBError) as caught:
        gateway.write("seller_profile", {})

    error = caught.value
    assert error.operation == "seller_profile"
    assert error.kind == "operation_mode_mismatch"
    assert error.retryable is False
    assert "read" in error.message


def test_gateway_validates_a_planned_write_without_needing_an_sdk_client() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    gateway.validate_write("set_prices", {"items": []})

    with pytest.raises(WBError) as caught:
        gateway.validate_write(
            "set_prices",
            {"items": [], "secret": "SECRET_MARKER"},
        )

    assert caught.value.kind == "invalid_payload"
    assert "SECRET_MARKER" not in caught.value.message


def test_gateway_adapts_empty_minus_phrases_as_an_explicit_clear() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    _, arguments = gateway._validated_arguments(
        "set_minus_phrases",
        {"campaign_id": 1, "nm_id": 2, "phrases": []},
        mutation=True,
    )

    request = arguments["v0_set_minus_norm_query_request"]
    assert getattr(request, "norm_queries") == []


def test_order_status_operation_is_registered_read_only_not_as_a_mutation() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    assert "update_order_status" not in OPERATIONS
    assert OPERATIONS["get_order_statuses"].mutation is False

    with pytest.raises(WBError) as caught:
        gateway.write("get_order_statuses", {"order_ids": [12345678]})

    assert caught.value.kind == "operation_mode_mismatch"


def test_gateway_normalizes_sdk_errors_without_exposing_tokens_or_urls() -> None:
    token = "secret-token"

    class RateLimitedError(Exception):
        status = 429

        def __str__(self) -> str:
            return "https://example.invalid failed with Authorization: secret-token"

    class General:
        def get_v1_seller_info(self) -> dict[str, object]:
            raise RateLimitedError

    gateway = WildberriesGateway(token, clients={"general": General()})

    with pytest.raises(WBError) as caught:
        gateway.read("seller_profile", {})

    error = caught.value
    assert error.operation == "seller_profile"
    assert error.kind == "rate_limited"
    assert error.retryable is True
    assert token not in error.message
    assert "https://" not in error.message


@pytest.mark.parametrize(
    ("operation", "payload", "mutation"),
    [
        ("tariffs_commission", {"locale": "ru"}, False),
        ("list_campaigns", {}, False),
        ("get_campaign", {"campaign_id": 1}, False),
        (
            "campaign_stats",
            {
                "campaign_ids": [1],
                "date_from": date(2026, 7, 1),
                "date_to": date(2026, 7, 2),
            },
            False,
        ),
        ("campaign_bids", {"campaign_id": 1, "nm_id": 2}, False),
        ("campaign_budget", {"campaign_id": 1}, False),
        ("search_clusters", {"campaign_id": 1, "nm_id": 2}, False),
        (
            "sales_funnel",
            {"nm_ids": [2], "date_from": date(2026, 7, 1), "date_to": date(2026, 7, 2)},
            False,
        ),
        (
            "search_queries",
            {
                "nm_ids": [2],
                "date_from": date(2026, 7, 1),
                "date_to": date(2026, 7, 2),
                "limit": 100,
                "offset": 0,
            },
            False,
        ),
        (
            "stock_analytics",
            {
                "nm_ids": [2],
                "date_from": date(2026, 7, 1),
                "date_to": date(2026, 7, 2),
                "stock_type": "",
            },
            False,
        ),
        ("report_status", {}, False),
        ("balance", {}, False),
        ("financial_documents", {"locale": "ru", "limit": 50, "offset": 0}, False),
        ("feedbacks", {"is_answered": False, "take": 10, "skip": 0}, False),
        ("questions", {"is_answered": False, "take": 10, "skip": 0}, False),
        ("chats", {}, False),
        ("chat_events", {}, False),
        (
            "create_campaign",
            {
                "name": "test",
                "nm_ids": [2],
                "bid_type": "manual",
                "payment_type": "cpm",
                "placement_types": ["search"],
            },
            True,
        ),
        ("pause_campaign", {"campaign_id": 1}, True),
        (
            "update_bids",
            {
                "campaign_id": 1,
                "bids": [{"nm_id": 2, "bid_kopecks": 10_000, "placement": "search"}],
            },
            True,
        ),
        (
            "set_minus_phrases",
            {"campaign_id": 1, "nm_id": 2, "phrases": ["query"]},
            True,
        ),
        (
            "start_report",
            {"nm_ids": [2], "date_from": date(2026, 7, 1), "date_to": date(2026, 7, 2)},
            True,
        ),
        ("reply_feedback", {"feedback_id": "id", "text": "text"}, True),
        ("reply_question", {"question_id": "id", "text": "text"}, True),
        ("send_chat_message", {"reply_sign": "sign", "message": "text"}, True),
        ("deposit_campaign_budget", {"campaign_id": 1, "amount": 3000}, True),
    ],
)
def test_remaining_operations_build_generated_sdk_arguments_without_network(
    operation: str, payload: dict[str, object], mutation: bool
) -> None:
    gateway = WildberriesGateway("test-token", clients={})
    registered, arguments = gateway._validated_arguments(
        operation, payload, mutation=mutation
    )
    clients = gateway_module._create_sdk_clients("test-token")
    public_parameters = {
        name
        for name in signature(
            getattr(clients[registered.client], registered.method)
        ).parameters
        if name != "self" and not name.startswith("_")
    }

    assert arguments.keys() <= public_parameters


def test_every_registered_operation_uses_a_public_installed_sdk_method() -> None:
    clients = gateway_module._create_sdk_clients("test-token")

    for operation in OPERATIONS.values():
        method = getattr(clients[operation.client], operation.method, None)
        assert callable(method), (operation.client, operation.method)


def test_financial_document_dates_are_adapted_to_sdk_argument_names() -> None:
    received: dict[str, object] = {}

    class Finances:
        def get_v1_documents_list(
            self,
            *,
            locale: str,
            begin_time: date,
            end_time: date,
            limit: int,
            offset: int,
        ) -> dict[str, bool]:
            received.update(
                {
                    "locale": locale,
                    "begin_time": begin_time,
                    "end_time": end_time,
                    "limit": limit,
                    "offset": offset,
                }
            )
            return {"ok": True}

    gateway = WildberriesGateway("test-token", clients={"finances": Finances()})

    assert gateway.read(
        "financial_documents",
        {
            "locale": "ru",
            "begin_date": date(2026, 7, 1),
            "end_date": date(2026, 7, 2),
            "limit": 50,
            "offset": 0,
        },
    ) == {"ok": True}
    assert received == {
        "locale": "ru",
        "begin_time": date(2026, 7, 1),
        "end_time": date(2026, 7, 2),
        "limit": 50,
        "offset": 0,
    }


def test_manual_campaign_creation_defaults_to_search_and_recommendations() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    _, arguments = gateway._validated_arguments(
        "create_campaign",
        {"name": "Новая кампания", "nm_ids": [987654321]},
        mutation=True,
    )
    request = arguments["adv_v2_seacat_save_ad_post_request"]

    assert getattr(request, "model_dump")(by_alias=True)["placement_types"] == [
        "search",
        "recommendations",
    ]
