from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from wb_mcp.gateway import WBError, WildberriesGateway


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
