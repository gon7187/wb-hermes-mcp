from dataclasses import dataclass
from datetime import date
from inspect import signature

import pytest
from pydantic import BaseModel
from wildberries_sdk.promotion.rest import RESTResponse

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


def test_campaign_stats_uses_the_sdk_raw_response_when_generated_enum_is_stale() -> (
    None
):
    received: dict[str, object] = {}

    class UnderlyingResponse:
        status = 200
        reason = "OK"
        headers: dict[str, str] = {}
        released = False
        read_amount: int | None = None

        def read(self, amount: int | None = None) -> bytes:
            self.read_amount = amount
            return (
                b'[{"advertId":1,"days":[{"apps":[{"appType":128}],'
                b'"date":"2026-07-23"}]}]'
            )

        def release_conn(self) -> None:
            self.released = True

    underlying = UnderlyingResponse()
    response = RESTResponse(underlying)

    class Promotion:
        def adv_v3_fullstats_get_without_preload_content(
            self,
            *,
            ids: str,
            begin_date: date,
            end_date: date,
        ) -> RESTResponse:
            received.update(
                {
                    "ids": ids,
                    "begin_date": begin_date,
                    "end_date": end_date,
                }
            )
            return response

    gateway = WildberriesGateway("test-token", clients={"promotion": Promotion()})

    result = gateway.read(
        "campaign_stats",
        {
            "campaign_ids": [1],
            "date_from": date(2026, 7, 23),
            "date_to": date(2026, 7, 23),
        },
    )

    assert result == {
        "data": [
            {
                "advertId": 1,
                "days": [
                    {
                        "apps": [{"appType": 128}],
                        "date": "2026-07-23",
                    }
                ],
            }
        ]
    }
    assert received == {
        "ids": "1",
        "begin_date": date(2026, 7, 23),
        "end_date": date(2026, 7, 23),
    }
    assert underlying.released is True
    assert underlying.read_amount == 128 * 1024 * 1024 + 1


def test_campaign_stats_maps_a_raw_429_without_exposing_the_body() -> None:
    class RawResponse:
        status = 429

        def read(self, amount: int | None = None) -> bytes:
            return b'{"detail":"SECRET_MARKER"}'

        def release_conn(self) -> None:
            pass

    class Promotion:
        def adv_v3_fullstats_get_without_preload_content(
            self,
            **kwargs: object,
        ) -> RawResponse:
            return RawResponse()

    gateway = WildberriesGateway("test-token", clients={"promotion": Promotion()})

    with pytest.raises(WBError) as caught:
        gateway.read(
            "campaign_stats",
            {
                "campaign_ids": [1],
                "date_from": date(2026, 7, 23),
                "date_to": date(2026, 7, 23),
            },
        )

    assert caught.value.kind == "rate_limited"
    assert caught.value.retryable is True
    assert "SECRET_MARKER" not in caught.value.message


def test_gateway_treats_sdk_status_zero_as_retryable_transport() -> None:
    class TransportError(Exception):
        status = 0

    class General:
        def get_v1_seller_info(self) -> dict[str, object]:
            raise TransportError

    gateway = WildberriesGateway("test-token", clients={"general": General()})

    with pytest.raises(WBError) as caught:
        gateway.read("seller_profile", {})

    assert caught.value.kind == "transport_error"
    assert caught.value.retryable is True


@pytest.mark.parametrize(
    ("operation", "payload", "mutation"),
    [
        ("tariffs_commission", {"locale": "ru"}, False),
        ("campaign_counts", {}, False),
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
        (
            "campaign_spend_history",
            {"date_from": date(2026, 7, 1), "date_to": date(2026, 7, 2)},
            False,
        ),
        (
            "minimum_campaign_bids",
            {
                "campaign_id": 1,
                "nm_ids": [2],
                "payment_type": "cpm",
                "placement_types": ["search"],
            },
            False,
        ),
        ("search_clusters", {"campaign_id": 1, "nm_id": 2}, False),
        ("list_sales", {"date_from": "2026-07-01T00:00:00", "flag": 0}, False),
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
        (
            "stock_products",
            {
                "date_from": date(2026, 7, 1),
                "date_to": date(2026, 7, 2),
                "stock_type": "",
                "skip_deleted_nm": True,
                "order_field": "stockCount",
                "order_mode": "asc",
                "availability_filters": [],
                "limit": 1000,
                "offset": 0,
            },
            False,
        ),
        (
            "wb_warehouse_stocks",
            {"limit": 250000, "offset": 0},
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
        ("delete_campaign", {"campaign_id": 1}, True),
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
        (
            "deposit_campaign_budget",
            {"campaign_id": 1, "amount": 3000, "source_type": 1},
            True,
        ),
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


def test_stock_product_request_matches_the_legacy_monitor_contract() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    _, arguments = gateway._validated_arguments(
        "stock_products",
        {
            "date_from": date(2026, 7, 1),
            "date_to": date(2026, 7, 2),
            "stock_type": "",
            "skip_deleted_nm": True,
            "order_field": "stockCount",
            "order_mode": "asc",
            "availability_filters": [],
            "limit": 1000,
            "offset": 0,
        },
        mutation=False,
    )

    request = arguments["table_item_request"]
    assert getattr(request, "model_dump")(mode="json", by_alias=True) == {
        "nmIDs": None,
        "subjectID": None,
        "brandName": None,
        "tagID": None,
        "currentPeriod": {"start": "2026-07-01", "end": "2026-07-02"},
        "stockType": "",
        "skipDeletedNm": True,
        "orderBy": {"field": "stockCount", "mode": "asc"},
        "availabilityFilters": [],
        "limit": 1000,
        "offset": 0,
    }


def test_warehouse_stock_request_uses_the_current_sdk_pagination_fields() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    _, arguments = gateway._validated_arguments(
        "wb_warehouse_stocks",
        {"nm_ids": [123], "limit": 250000, "offset": 0},
        mutation=False,
    )

    request = arguments["inventory_request"]
    assert getattr(request, "model_dump")(mode="json", by_alias=True) == {
        "nmIds": [123],
        "chrtIds": None,
        "limit": 250000,
        "offset": 0,
    }


def test_deposit_forwards_the_explicit_balance_source_in_rubles() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    _, arguments = gateway._validated_arguments(
        "deposit_campaign_budget",
        {"campaign_id": 77, "amount": 3000, "source_type": 1},
        mutation=True,
    )

    request = arguments["adv_v1_budget_deposit_post_request"]
    body = getattr(request, "model_dump")(mode="json", by_alias=True)
    assert body["sum"] == 3000
    assert body["type"] == 1


def test_deposit_rejects_an_amount_below_the_documented_minimum() -> None:
    gateway = WildberriesGateway("test-token", clients={})

    with pytest.raises(WBError) as caught:
        gateway.validate_write(
            "deposit_campaign_budget",
            {"campaign_id": 77, "amount": 999, "source_type": 1},
        )

    assert caught.value.kind == "invalid_payload"
