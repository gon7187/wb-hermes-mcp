"""Safe, named dispatch for generated Wildberries SDK clients."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Final, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from wildberries_sdk import general, items, orders_fbs


JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
PayloadAdapter: TypeAlias = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class Operation:
    """One named SDK operation that the MCP server is allowed to call."""

    client: str
    method: str
    mutation: bool = False
    payload_adapter: PayloadAdapter | None = None


class WBError(Exception):
    """A compact error that is safe to expose through an MCP tool."""

    def __init__(
        self,
        *,
        operation: str,
        kind: str,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.kind = kind
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
        }


def _adapt_price_upload(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Build the generated request object for the named price-upload operation."""

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > 1_000:
        raise ValueError("price upload items are invalid")

    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ValueError("price upload item is invalid")
        if item.get("price") is None and item.get("discount") is None:
            raise ValueError("price upload item lacks both price and discount")

    request = items.ApiV2UploadTaskPostRequest.model_validate({"data": raw_items})
    return {"api_v2_upload_task_post_request": request}


def _require_empty_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Reject user input for SDK operations that take no public arguments."""

    if payload:
        raise ValueError("operation takes no payload")
    return {}


def _allow_only(payload: Mapping[str, object], allowed: set[str]) -> None:
    """Reject unknown public arguments before they can reach generated clients."""

    if any(key not in allowed for key in payload):
        raise ValueError("payload has unsupported fields")


def _require_value(payload: Mapping[str, object], key: str) -> object:
    """Return a required public field without exposing its value on failure."""

    value = payload.get(key)
    if value is None:
        raise ValueError("payload lacks a required field")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = _require_value(payload, key)
    if type(value) is not int:
        raise ValueError("payload field must be an integer")
    return value


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = _require_value(payload, key)
    if not isinstance(value, str) or not value:
        raise ValueError("payload field must be a non-empty string")
    return value


def _require_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = _require_value(payload, key)
    if not isinstance(value, list):
        raise ValueError("payload field must be a list")
    return value


def _copy_optional(
    arguments: Mapping[str, object],
    payload: Mapping[str, object],
    *keys: str,
) -> dict[str, object]:
    """Copy explicit, non-null public fields into generated SDK arguments."""

    result = dict(arguments)
    for key in keys:
        if key in payload and payload[key] is not None:
            result[key] = payload[key]
    return result


def _adapt_list_cards(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"settings", "locale"})
    request = items.ContentV2GetCardsListPostRequest.model_validate(
        {"settings": payload.get("settings")}
    )
    return _copy_optional(
        {"content_v2_get_cards_list_post_request": request}, payload, "locale"
    )


def _adapt_card_schema_parents(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"locale"})
    return _copy_optional({}, payload, "locale")


def _adapt_card_schema_subjects(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"locale", "name", "limit", "offset", "parent_id"})
    return _copy_optional({}, payload, "locale", "name", "limit", "offset", "parent_id")


def _adapt_card_schema_characteristics(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(payload, {"subject_id", "locale"})
    arguments = {"subject_id": _require_int(payload, "subject_id")}
    return _copy_optional(arguments, payload, "locale")


def _adapt_card_errors(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"cursor", "order", "locale"})
    request = items.RequestPublicViewerPublicErrorsTableListV2.model_validate(
        {"cursor": payload.get("cursor"), "order": payload.get("order")}
    )
    return _copy_optional(
        {"request_public_viewer_public_errors_table_list_v2": request},
        payload,
        "locale",
    )


def _adapt_list_prices(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"limit", "offset", "filter_nm_id"})
    arguments = {"limit": _require_int(payload, "limit")}
    return _copy_optional(arguments, payload, "offset", "filter_nm_id")


def _adapt_get_stocks(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"warehouse_id", "chrt_ids"})
    request = items.ApiV3StocksWarehouseIdPostRequest.model_validate(
        {"chrtIds": _require_list(payload, "chrt_ids")}
    )
    return {
        "warehouse_id": _require_int(payload, "warehouse_id"),
        "api_v3_stocks_warehouse_id_post_request": request,
    }


def _adapt_list_orders(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"limit", "next", "date_from", "date_to"})
    arguments = {
        "limit": _require_int(payload, "limit"),
        "next": _require_int(payload, "next"),
    }
    return _copy_optional(arguments, payload, "date_from", "date_to")


def _adapt_order_stickers(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"type", "width", "height", "order_ids"})
    order_ids = _require_list(payload, "order_ids")
    if not order_ids:
        raise ValueError("stickers require at least one order")
    request = orders_fbs.ApiV3OrdersStickersPostRequest.model_validate(
        {"orders": order_ids}
    )
    return {
        "type": _require_str(payload, "type"),
        "width": _require_int(payload, "width"),
        "height": _require_int(payload, "height"),
        "api_v3_orders_stickers_post_request": request,
    }


def _adapt_list_supplies(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"limit", "next"})
    return {
        "limit": _require_int(payload, "limit"),
        "next": _require_int(payload, "next"),
    }


def _adapt_get_supply(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"supply_id"})
    return {"supply_id": _require_str(payload, "supply_id")}


def _adapt_get_supply_barcode(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"supply_id", "type"})
    return {
        "supply_id": _require_str(payload, "supply_id"),
        "type": _require_str(payload, "type"),
    }


def _adapt_update_cards(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"cards"})
    cards = _require_list(payload, "cards")
    if not cards or len(cards) > 3_000:
        raise ValueError("card update items are invalid")
    requests = []
    for card in cards:
        if not isinstance(card, Mapping):
            raise ValueError("card update item is invalid")
        # The SDK defaults a missing kizMarked to false. Explicit None preserves a
        # partial update by omitting the field from the generated request body.
        card_payload = dict(card)
        card_payload.setdefault("kizMarked", None)
        requests.append(
            items.ContentV2CardsUpdatePostRequestInner.model_validate(card_payload)
        )
    return {"content_v2_cards_update_post_request_inner": requests}


def _adapt_save_media(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"nm_id", "media_urls"})
    media_urls = _require_list(payload, "media_urls")
    if not media_urls or not all(isinstance(url, str) and url for url in media_urls):
        raise ValueError("media URLs are invalid")
    request = items.ContentV3MediaSavePostRequest.model_validate(
        {"nmId": _require_int(payload, "nm_id"), "data": media_urls}
    )
    return {"content_v3_media_save_post_request": request}


def _adapt_set_stocks(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"warehouse_id", "stocks"})
    stocks = _require_list(payload, "stocks")
    if not stocks:
        raise ValueError("stocks must not be empty")
    request = items.ApiV3StocksWarehouseIdPutRequest.model_validate({"stocks": stocks})
    return {
        "warehouse_id": _require_int(payload, "warehouse_id"),
        "api_v3_stocks_warehouse_id_put_request": request,
    }


def _adapt_create_warehouse(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"name", "office_id"})
    request = items.ApiV3WarehousesPostRequest.model_validate(
        {
            "name": _require_str(payload, "name"),
            "officeId": _require_int(payload, "office_id"),
        }
    )
    return {"api_v3_warehouses_post_request": request}


def _adapt_update_warehouse(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"warehouse_id", "name", "office_id"})
    request = items.ApiV3WarehousesPostRequest.model_validate(
        {
            "name": _require_str(payload, "name"),
            "officeId": _require_int(payload, "office_id"),
        }
    )
    return {
        "warehouse_id": _require_int(payload, "warehouse_id"),
        "api_v3_warehouses_post_request": request,
    }


def _adapt_delete_warehouse(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"warehouse_id"})
    return {"warehouse_id": _require_int(payload, "warehouse_id")}


def _adapt_update_order_status(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"order_ids"})
    order_ids = _require_list(payload, "order_ids")
    if not order_ids:
        raise ValueError("order IDs must not be empty")
    request = orders_fbs.ApiV3OrdersStatusPostRequest.model_validate(
        {"orders": order_ids}
    )
    return {"api_v3_orders_status_post_request": request}


def _adapt_cancel_order(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"order_id"})
    return {"order_id": _require_int(payload, "order_id")}


def _adapt_create_supply(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"name"})
    request = orders_fbs.ApiV3SuppliesPostRequest.model_validate(
        {"name": _require_str(payload, "name")}
    )
    return {"api_v3_supplies_post_request": request}


def _adapt_attach_supply_orders(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"supply_id", "order_ids"})
    order_ids = _require_list(payload, "order_ids")
    if not order_ids:
        raise ValueError("supply order IDs must not be empty")
    request = (
        orders_fbs.ApiMarketplaceV3SuppliesSupplyIdOrdersPatchRequest.model_validate(
            {"orders": order_ids}
        )
    )
    return {
        "supply_id": _require_str(payload, "supply_id"),
        "api_marketplace_v3_supplies_supply_id_orders_patch_request": request,
    }


def _adapt_supply_id(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"supply_id"})
    return {"supply_id": _require_str(payload, "supply_id")}


OPERATIONS: Final[Mapping[str, Operation]] = MappingProxyType(
    {
        "seller_profile": Operation(
            client="general",
            method="get_v1_seller_info",
            payload_adapter=_require_empty_payload,
        ),
        "set_prices": Operation(
            client="items",
            method="api_v2_upload_task_post",
            mutation=True,
            payload_adapter=_adapt_price_upload,
        ),
        "list_cards": Operation(
            client="items",
            method="content_v2_get_cards_list_post",
            payload_adapter=_adapt_list_cards,
        ),
        "card_schema_parents": Operation(
            client="items",
            method="content_v2_object_parent_all_get",
            payload_adapter=_adapt_card_schema_parents,
        ),
        "card_schema_subjects": Operation(
            client="items",
            method="content_v2_object_all_get",
            payload_adapter=_adapt_card_schema_subjects,
        ),
        "card_schema_characteristics": Operation(
            client="items",
            method="content_v2_object_charcs_subject_id_get",
            payload_adapter=_adapt_card_schema_characteristics,
        ),
        "list_card_errors": Operation(
            client="items",
            method="content_v2_cards_error_list_post",
            payload_adapter=_adapt_card_errors,
        ),
        "list_tags": Operation(
            client="items",
            method="content_v2_tags_get",
            payload_adapter=_require_empty_payload,
        ),
        "list_prices": Operation(
            client="items",
            method="api_v2_list_goods_filter_get",
            payload_adapter=_adapt_list_prices,
        ),
        "get_stocks": Operation(
            client="items",
            method="api_v3_stocks_warehouse_id_post",
            payload_adapter=_adapt_get_stocks,
        ),
        "list_warehouses": Operation(
            client="items",
            method="api_v3_warehouses_get",
            payload_adapter=_require_empty_payload,
        ),
        "list_orders": Operation(
            client="orders_fbs",
            method="api_v3_orders_get",
            payload_adapter=_adapt_list_orders,
        ),
        "get_order_details": Operation(
            client="orders_fbs",
            method="api_v3_orders_new_get",
            payload_adapter=_require_empty_payload,
        ),
        "get_order_stickers": Operation(
            client="orders_fbs",
            method="api_v3_orders_stickers_post",
            payload_adapter=_adapt_order_stickers,
        ),
        "list_supplies": Operation(
            client="orders_fbs",
            method="api_v3_supplies_get",
            payload_adapter=_adapt_list_supplies,
        ),
        "get_supply": Operation(
            client="orders_fbs",
            method="api_v3_supplies_supply_id_get",
            payload_adapter=_adapt_get_supply,
        ),
        "get_supply_barcode": Operation(
            client="orders_fbs",
            method="api_v3_supplies_supply_id_barcode_get",
            payload_adapter=_adapt_get_supply_barcode,
        ),
        "update_cards": Operation(
            client="items",
            method="content_v2_cards_update_post",
            mutation=True,
            payload_adapter=_adapt_update_cards,
        ),
        "save_media": Operation(
            client="items",
            method="content_v3_media_save_post",
            mutation=True,
            payload_adapter=_adapt_save_media,
        ),
        "set_stocks": Operation(
            client="items",
            method="api_v3_stocks_warehouse_id_put",
            mutation=True,
            payload_adapter=_adapt_set_stocks,
        ),
        "create_warehouse": Operation(
            client="items",
            method="api_v3_warehouses_post",
            mutation=True,
            payload_adapter=_adapt_create_warehouse,
        ),
        "update_warehouse": Operation(
            client="items",
            method="api_v3_warehouses_warehouse_id_put",
            mutation=True,
            payload_adapter=_adapt_update_warehouse,
        ),
        "delete_warehouse": Operation(
            client="items",
            method="api_v3_warehouses_warehouse_id_delete",
            mutation=True,
            payload_adapter=_adapt_delete_warehouse,
        ),
        "update_order_status": Operation(
            client="orders_fbs",
            method="api_v3_orders_status_post",
            mutation=True,
            payload_adapter=_adapt_update_order_status,
        ),
        "cancel_order": Operation(
            client="orders_fbs",
            method="api_v3_orders_order_id_cancel_patch",
            mutation=True,
            payload_adapter=_adapt_cancel_order,
        ),
        "create_supply": Operation(
            client="orders_fbs",
            method="api_v3_supplies_post",
            mutation=True,
            payload_adapter=_adapt_create_supply,
        ),
        "attach_supply_orders": Operation(
            client="orders_fbs",
            method="api_marketplace_v3_supplies_supply_id_orders_patch",
            mutation=True,
            payload_adapter=_adapt_attach_supply_orders,
        ),
        "deliver_supply": Operation(
            client="orders_fbs",
            method="api_v3_supplies_supply_id_deliver_patch",
            mutation=True,
            payload_adapter=_adapt_supply_id,
        ),
        "delete_supply": Operation(
            client="orders_fbs",
            method="api_v3_supplies_supply_id_delete",
            mutation=True,
            payload_adapter=_adapt_supply_id,
        ),
    }
)


def _create_sdk_clients(token: str) -> dict[str, object]:
    """Create isolated generated SDK clients without issuing a request."""

    return {
        "general": general.DefaultApi(
            general.ApiClient(general.Configuration(api_key={"HeaderApiKey": token}))
        ),
        "items": items.DefaultApi(
            items.ApiClient(items.Configuration(api_key={"HeaderApiKey": token}))
        ),
        "orders_fbs": orders_fbs.DefaultApi(
            orders_fbs.ApiClient(
                orders_fbs.Configuration(api_key={"HeaderApiKey": token})
            )
        ),
    }


def _to_json_value(value: object) -> JsonValue:
    """Recursively turn common SDK response types into JSON-compatible values."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return _to_json_value(
            value.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
    if is_dataclass(value) and not isinstance(value, type):
        return _to_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_to_json_value(item) for item in value]
    raise TypeError(f"unsupported response type: {type(value).__name__}")


def _as_result(value: object) -> dict[str, object]:
    serialized = _to_json_value(value)
    if isinstance(serialized, dict):
        return cast(dict[str, object], serialized)
    return {"data": serialized}


class WildberriesGateway:
    """Dispatch only registry-listed operations to generated SDK clients."""

    def __init__(self, token: str, clients: Mapping[str, object] | None = None) -> None:
        self._clients = (
            dict(clients) if clients is not None else _create_sdk_clients(token)
        )

    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        return self._invoke(operation, payload, mutation=False)

    def write(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        return self._invoke(operation, payload, mutation=True)

    def validate_write(self, operation: str, payload: dict[str, object]) -> None:
        """Validate a planned write without constructing a network request."""

        self._validated_arguments(operation, payload, mutation=True)

    def _validated_arguments(
        self,
        operation_name: str,
        payload: Mapping[str, object],
        *,
        mutation: bool,
    ) -> tuple[Operation, Mapping[str, object]]:
        operation = OPERATIONS.get(operation_name)
        if operation is None:
            raise WBError(
                operation="unknown",
                kind="unknown_operation",
                message="Unknown operation. Only named Wildberries MCP operations are available.",
                retryable=False,
            )
        if operation.mutation != mutation:
            mode = "write" if operation.mutation else "read"
            raise WBError(
                operation=operation_name,
                kind="operation_mode_mismatch",
                message=f"This operation must be called through {mode}().",
                retryable=False,
            )
        try:
            arguments = (
                operation.payload_adapter(payload)
                if operation.payload_adapter is not None
                else payload
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise WBError(
                operation=operation_name,
                kind="invalid_payload",
                message="Payload is invalid for this Wildberries operation.",
                retryable=False,
            ) from error
        return operation, arguments

    def _invoke(
        self,
        operation_name: str,
        payload: Mapping[str, object],
        *,
        mutation: bool,
    ) -> dict[str, object]:
        operation, arguments = self._validated_arguments(
            operation_name, payload, mutation=mutation
        )

        client = self._clients.get(operation.client)
        if client is None:
            raise WBError(
                operation=operation_name,
                kind="client_unavailable",
                message="The required Wildberries SDK client is unavailable.",
                retryable=False,
            )
        method = getattr(client, operation.method, None)
        if not callable(method):
            raise WBError(
                operation=operation_name,
                kind="sdk_method_unavailable",
                message="The required Wildberries SDK method is unavailable.",
                retryable=False,
            )

        try:
            response = method(**arguments)
        except Exception as error:
            raise self._sdk_error(operation_name, error) from None

        try:
            return _as_result(response)
        except (TypeError, ValueError) as error:
            raise WBError(
                operation=operation_name,
                kind="serialization_error",
                message="Wildberries returned a response that cannot be serialized safely.",
                retryable=False,
            ) from error

    @staticmethod
    def _sdk_error(operation: str, error: Exception) -> WBError:
        status = getattr(error, "status", None)
        if status == 429:
            return WBError(
                operation=operation,
                kind="rate_limited",
                message="Wildberries rate limit reached; retry later.",
                retryable=True,
            )
        if isinstance(status, int) and status >= 500:
            return WBError(
                operation=operation,
                kind="service_unavailable",
                message="Wildberries service is temporarily unavailable; retry later.",
                retryable=True,
            )
        if isinstance(status, int) and 400 <= status < 500:
            return WBError(
                operation=operation,
                kind="request_rejected",
                message="Wildberries rejected this request; review the payload.",
                retryable=False,
            )
        if isinstance(error, TimeoutError | ConnectionError):
            return WBError(
                operation=operation,
                kind="transport_error",
                message="Wildberries request could not be completed; retry later.",
                retryable=True,
            )
        return WBError(
            operation=operation,
            kind="sdk_error",
            message="Wildberries SDK request failed.",
            retryable=False,
        )
