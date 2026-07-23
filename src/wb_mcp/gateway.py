"""Safe, named dispatch for generated Wildberries SDK clients."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Final, TypeAlias, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from wildberries_sdk import (
    analytics,
    communications,
    finances,
    general,
    items,
    orders_fbs,
    promotion,
    rates,
    reports,
)


JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
PayloadAdapter: TypeAlias = Callable[[Mapping[str, object]], Mapping[str, object]]
MAX_RAW_RESPONSE_BYTES: Final = 128 * 1024 * 1024


@dataclass(frozen=True)
class Operation:
    """One named SDK operation that the MCP server is allowed to call."""

    client: str
    method: str
    mutation: bool = False
    payload_adapter: PayloadAdapter | None = None
    raw_json: bool = False


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


class _RawResponseStatusError(Exception):
    """Carry only an HTTP status from a generated SDK raw response."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__("Wildberries returned an unsuccessful HTTP status.")


def _read_raw_json_response(response: object) -> object:
    """Decode an SDK raw response without relying on stale generated enums."""

    transport = getattr(response, "response", response)
    read = getattr(transport, "read", None)
    release = getattr(transport, "release_conn", None)
    if not callable(read):
        raise TypeError("SDK raw response cannot be read")
    try:
        body = read(MAX_RAW_RESPONSE_BYTES + 1)
        status = getattr(response, "status", None)
        if isinstance(status, int) and not 200 <= status < 300:
            raise _RawResponseStatusError(status)
        if not isinstance(body, bytes) or len(body) > MAX_RAW_RESPONSE_BYTES:
            raise ValueError("SDK raw response has an invalid size")
        return json.loads(body)
    finally:
        if callable(release):
            release()


def _adapt_price_upload(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Build the generated request object for the named price-upload operation."""

    _allow_only(payload, {"items"})
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


def _adapt_get_order_statuses(payload: Mapping[str, object]) -> Mapping[str, object]:
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


def _require_date(payload: Mapping[str, object], key: str) -> date:
    value = _require_value(payload, key)
    if not isinstance(value, date):
        raise ValueError("payload field must be a date")
    return value


def _adapt_tariffs_commission(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"locale"})
    return _copy_optional({}, payload, "locale")


def _adapt_tariffs_by_date(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"date"})
    value = _require_value(payload, "date")
    if not isinstance(value, str) or not value:
        raise ValueError("tariff date is invalid")
    return {"var_date": value}


def _adapt_acceptance_coefficients(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(payload, {"warehouse_ids"})
    warehouse_ids = payload.get("warehouse_ids")
    if warehouse_ids is None:
        return {}
    if not isinstance(warehouse_ids, list) or not all(
        type(warehouse_id) is int for warehouse_id in warehouse_ids
    ):
        raise ValueError("warehouse IDs are invalid")
    return {
        "warehouse_ids": ",".join(str(warehouse_id) for warehouse_id in warehouse_ids)
    }


def _join_ints(values: object, *, field: str, maximum: int = 50) -> str:
    if not isinstance(values, list) or not values or len(values) > maximum:
        raise ValueError(f"{field} are invalid")
    if not all(type(value) is int for value in values):
        raise ValueError(f"{field} are invalid")
    return ",".join(str(value) for value in values)


def _adapt_list_campaigns(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_ids", "statuses", "payment_type"})
    arguments: dict[str, object] = {}
    if "campaign_ids" in payload:
        arguments["ids"] = _join_ints(payload["campaign_ids"], field="campaign IDs")
    if "statuses" in payload:
        arguments["statuses"] = _join_ints(
            payload["statuses"], field="campaign statuses"
        )
    return _copy_optional(arguments, payload, "payment_type")


def _adapt_get_campaign(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id"})
    return {"ids": str(_require_int(payload, "campaign_id"))}


def _adapt_campaign_stats(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_ids", "date_from", "date_to"})
    return {
        "ids": _join_ints(payload.get("campaign_ids"), field="campaign IDs"),
        "begin_date": _require_date(payload, "date_from"),
        "end_date": _require_date(payload, "date_to"),
    }


def _adapt_campaign_spend_history(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(payload, {"date_from", "date_to"})
    return {
        "var_from": _require_date(payload, "date_from"),
        "to": _require_date(payload, "date_to"),
    }


def _adapt_campaign_bids(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "nm_id"})
    return {
        "advert_id": _require_int(payload, "campaign_id"),
        "nm_id": _require_int(payload, "nm_id"),
    }


def _adapt_minimum_campaign_bids(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(
        payload,
        {"campaign_id", "nm_ids", "payment_type", "placement_types"},
    )
    request = promotion.ApiAdvertV1BidsMinPostRequest.model_validate(
        {
            "advert_id": _require_int(payload, "campaign_id"),
            "nm_ids": _require_list(payload, "nm_ids"),
            "payment_type": _require_str(payload, "payment_type"),
            "placement_types": _require_list(payload, "placement_types"),
        }
    )
    return {"api_advert_v1_bids_min_post_request": request}


def _adapt_campaign_id(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id"})
    return {"id": _require_int(payload, "campaign_id")}


def _adapt_search_clusters(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "nm_id"})
    request = promotion.V0GetNormQueryListRequest.model_validate(
        {
            "items": [
                {
                    "advertId": _require_int(payload, "campaign_id"),
                    "nmId": _require_int(payload, "nm_id"),
                }
            ]
        }
    )
    return {"v0_get_norm_query_list_request": request}


def _adapt_list_sales(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"date_from", "flag"})
    arguments: dict[str, object] = {
        "date_from": _require_str(payload, "date_from"),
    }
    return _copy_optional(arguments, payload, "flag")


def _adapt_sales_funnel(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"nm_ids", "date_from", "date_to"})
    request = analytics.ItemsRequest.model_validate(
        {
            "selectedPeriod": {
                "start": _require_date(payload, "date_from"),
                "end": _require_date(payload, "date_to"),
            },
            "nmIds": _require_list(payload, "nm_ids"),
        }
    )
    return {"items_request": request}


def _adapt_search_queries(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"nm_ids", "date_from", "date_to", "limit", "offset"})
    request = analytics.MainRequest.model_validate(
        {
            "currentPeriod": {
                "start": _require_date(payload, "date_from"),
                "end": _require_date(payload, "date_to"),
            },
            "nmIds": _require_list(payload, "nm_ids"),
            "positionCluster": "all",
            "orderBy": {"field": "avgPosition", "mode": "asc"},
            "limit": payload.get("limit", 100),
            "offset": payload.get("offset", 0),
        }
    )
    return {"main_request": request}


def _adapt_stock_analytics(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"nm_ids", "date_from", "date_to", "stock_type"})
    request = analytics.CommonShippingOfficeFilters.model_validate(
        {
            "nmIDs": _require_list(payload, "nm_ids"),
            "currentPeriod": {
                "start": _require_date(payload, "date_from"),
                "end": _require_date(payload, "date_to"),
            },
            "stockType": payload.get("stock_type", ""),
            "skipDeletedNm": False,
        }
    )
    return {"body": request}


def _adapt_stock_products(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(
        payload,
        {
            "nm_ids",
            "subject_id",
            "brand_name",
            "tag_id",
            "date_from",
            "date_to",
            "stock_type",
            "skip_deleted_nm",
            "order_field",
            "order_mode",
            "availability_filters",
            "limit",
            "offset",
        },
    )
    request = analytics.TableItemRequest.model_validate(
        {
            "nmIDs": payload.get("nm_ids"),
            "subjectID": payload.get("subject_id"),
            "brandName": payload.get("brand_name"),
            "tagID": payload.get("tag_id"),
            "currentPeriod": {
                "start": _require_date(payload, "date_from"),
                "end": _require_date(payload, "date_to"),
            },
            "stockType": payload.get("stock_type", ""),
            "skipDeletedNm": payload.get("skip_deleted_nm", True),
            "orderBy": {
                "field": payload.get("order_field", "stockCount"),
                "mode": payload.get("order_mode", "asc"),
            },
            "availabilityFilters": payload.get("availability_filters", []),
            "limit": payload.get("limit", 1000),
            "offset": payload.get("offset", 0),
        }
    )
    return {"table_item_request": request}


def _adapt_wb_warehouse_stocks(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(payload, {"nm_ids", "chrt_ids", "limit", "offset"})
    request = analytics.InventoryRequest.model_validate(
        {
            "nmIds": payload.get("nm_ids"),
            "chrtIds": payload.get("chrt_ids"),
            "limit": payload.get("limit", 250_000),
            "offset": payload.get("offset", 0),
        }
    )
    return {"inventory_request": request}


def _adapt_report_status(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"download_ids"})
    raw_ids = payload.get("download_ids")
    if raw_ids is None:
        return {}
    if not isinstance(raw_ids, list):
        raise ValueError("report download IDs are invalid")
    try:
        return {"filter_download_ids": [UUID(str(value)) for value in raw_ids]}
    except (TypeError, ValueError) as error:
        raise ValueError("report download IDs are invalid") from error


def _adapt_financial_documents(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(
        payload,
        {
            "locale",
            "begin_date",
            "end_date",
            "sort",
            "order",
            "category",
            "limit",
            "offset",
        },
    )
    arguments = _copy_optional(
        {},
        payload,
        "locale",
        "sort",
        "order",
        "category",
        "limit",
        "offset",
    )
    if "begin_date" in payload:
        arguments["begin_time"] = payload["begin_date"]
    if "end_date" in payload:
        arguments["end_time"] = payload["end_date"]
    return arguments


def _adapt_feedbacks(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(
        payload,
        {"is_answered", "take", "skip", "nm_id", "order", "date_from", "date_to"},
    )
    return _copy_optional(
        {
            "is_answered": payload.get("is_answered", False),
            "take": payload.get("take", 100),
            "skip": payload.get("skip", 0),
        },
        payload,
        "nm_id",
        "order",
        "date_from",
        "date_to",
    )


def _adapt_questions(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(
        payload,
        {"is_answered", "take", "skip", "nm_id", "order", "date_from", "date_to"},
    )
    return _copy_optional(
        {
            "is_answered": payload.get("is_answered", False),
            "take": payload.get("take", 100),
            "skip": payload.get("skip", 0),
        },
        payload,
        "nm_id",
        "order",
        "date_from",
        "date_to",
    )


def _adapt_chat_events(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"next"})
    return _copy_optional({}, payload, "next")


def _adapt_create_campaign(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(
        payload, {"name", "nm_ids", "bid_type", "payment_type", "placement_types"}
    )
    bid_type = payload.get("bid_type", "manual")
    placement_types = payload.get("placement_types")
    if bid_type == "manual" and placement_types is None:
        placement_types = ["search", "recommendations"]
    if bid_type == "unified" and placement_types is not None:
        raise ValueError("unified campaign cannot set placement types")
    request = promotion.AdvV2SeacatSaveAdPostRequest.model_validate(
        {
            "name": _require_str(payload, "name"),
            "nms": payload.get("nm_ids"),
            "bid_type": bid_type,
            "payment_type": payload.get("payment_type", "cpm"),
            "placement_types": placement_types,
        }
    )
    return {"adv_v2_seacat_save_ad_post_request": request}


def _adapt_rename_campaign(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "name"})
    request = promotion.AdvV0RenamePostRequest.model_validate(
        {
            "advertId": _require_int(payload, "campaign_id"),
            "name": _require_str(payload, "name"),
        }
    )
    return {"adv_v0_rename_post_request": request}


def _adapt_update_bids(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "bids"})
    bids = _require_list(payload, "bids")
    if not bids:
        raise ValueError("campaign bids must not be empty")
    request = promotion.ApiAdvertV1BidsPatchRequest.model_validate(
        {
            "bids": [
                {
                    "advert_id": _require_int(payload, "campaign_id"),
                    "nm_bids": bids,
                }
            ]
        }
    )
    return {"api_advert_v1_bids_patch_request": request}


def _adapt_set_minus_phrases(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "nm_id", "phrases"})
    phrases = _require_list(payload, "phrases")
    if not all(isinstance(phrase, str) and phrase for phrase in phrases):
        raise ValueError("minus phrases are invalid")
    request = promotion.V0SetMinusNormQueryRequest.model_validate(
        {
            "advert_id": _require_int(payload, "campaign_id"),
            "nm_id": _require_int(payload, "nm_id"),
            "norm_queries": phrases,
        }
    )
    return {"v0_set_minus_norm_query_request": request}


def _adapt_start_report(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"nm_ids", "date_from", "date_to", "name"})
    raw_name = payload.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        raise ValueError("report name is invalid")
    raw_nm_ids = _require_list(payload, "nm_ids")
    if not raw_nm_ids or not all(type(nm_id) is int for nm_id in raw_nm_ids):
        raise ValueError("report nm IDs are invalid")
    report = analytics.SalesFunnelItemReq(
        id=uuid4(),
        reportType="DETAIL_HISTORY_REPORT",
        userReportName=raw_name,
        params=analytics.SalesFunnelItemReqParams(
            nmIDs=cast(list[int], raw_nm_ids),
            startDate=_require_date(payload, "date_from"),
            endDate=_require_date(payload, "date_to"),
        ),
    )
    return {
        "api_v2_nm_report_downloads_post_request": analytics.ApiV2NmReportDownloadsPostRequest(
            report
        )
    }


def _adapt_reply_feedback(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"feedback_id", "text"})
    request = communications.ApiV1FeedbacksAnswerPostRequest.model_validate(
        {
            "id": _require_str(payload, "feedback_id"),
            "text": _require_str(payload, "text"),
        }
    )
    return {"api_v1_feedbacks_answer_post_request": request}


def _adapt_reply_question(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"question_id", "text"})
    answer = communications.ApiV1QuestionsPatchRequestOneOf1.model_validate(
        {
            "id": _require_str(payload, "question_id"),
            "answer": {"text": _require_str(payload, "text")},
            "state": "wbRu",
        }
    )
    return {
        "api_v1_questions_patch_request": communications.ApiV1QuestionsPatchRequest(
            answer
        )
    }


def _adapt_send_chat_message(payload: Mapping[str, object]) -> Mapping[str, object]:
    _allow_only(payload, {"reply_sign", "message"})
    return {
        "reply_sign": _require_str(payload, "reply_sign"),
        "message": _require_str(payload, "message"),
    }


def _adapt_deposit_campaign_budget(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    _allow_only(payload, {"campaign_id", "amount", "source_type"})
    amount = _require_int(payload, "amount")
    if amount < 1_000:
        raise ValueError("campaign budget deposit is below the documented minimum")
    source_type = payload.get("source_type", 1)
    if type(source_type) is not int or source_type not in {0, 1, 3}:
        raise ValueError("campaign budget source type is invalid")
    request = promotion.AdvV1BudgetDepositPostRequest.model_validate(
        {"sum": amount, "type": source_type}
    )
    return {
        "id": _require_int(payload, "campaign_id"),
        "adv_v1_budget_deposit_post_request": request,
    }


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
        "list_new_orders": Operation(
            client="orders_fbs",
            method="api_v3_orders_new_get",
            payload_adapter=_require_empty_payload,
        ),
        "get_order_statuses": Operation(
            client="orders_fbs",
            method="api_v3_orders_status_post",
            payload_adapter=_adapt_get_order_statuses,
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
        "tariffs_commission": Operation(
            client="rates",
            method="get_v1_tariffs_commission",
            payload_adapter=_adapt_tariffs_commission,
        ),
        "tariffs_box": Operation(
            client="rates",
            method="get_v1_tariffs_box",
            payload_adapter=_adapt_tariffs_by_date,
        ),
        "tariffs_pallet": Operation(
            client="rates",
            method="get_v1_tariffs_pallet",
            payload_adapter=_adapt_tariffs_by_date,
        ),
        "tariffs_return": Operation(
            client="rates",
            method="get_v1_tariffs_return",
            payload_adapter=_adapt_tariffs_by_date,
        ),
        "acceptance_coefficients": Operation(
            client="rates",
            method="get_v1_acceptance_coefficients",
            payload_adapter=_adapt_acceptance_coefficients,
        ),
        "campaign_counts": Operation(
            client="promotion",
            method="adv_v1_promotion_count_get",
            payload_adapter=_require_empty_payload,
        ),
        "list_campaigns": Operation(
            client="promotion",
            method="api_advert_v2_adverts_get",
            payload_adapter=_adapt_list_campaigns,
        ),
        "get_campaign": Operation(
            client="promotion",
            method="api_advert_v2_adverts_get",
            payload_adapter=_adapt_get_campaign,
        ),
        "campaign_stats": Operation(
            client="promotion",
            method="adv_v3_fullstats_get_without_preload_content",
            payload_adapter=_adapt_campaign_stats,
            raw_json=True,
        ),
        "campaign_spend_history": Operation(
            client="promotion",
            method="adv_v1_upd_get",
            payload_adapter=_adapt_campaign_spend_history,
        ),
        "campaign_bids": Operation(
            client="promotion",
            method="api_advert_v0_bids_recommendations_get",
            payload_adapter=_adapt_campaign_bids,
        ),
        "minimum_campaign_bids": Operation(
            client="promotion",
            method="api_advert_v1_bids_min_post",
            payload_adapter=_adapt_minimum_campaign_bids,
        ),
        "campaign_budget": Operation(
            client="promotion",
            method="adv_v1_budget_get",
            payload_adapter=_adapt_campaign_id,
        ),
        "search_clusters": Operation(
            client="promotion",
            method="adv_v0_normquery_list_post",
            payload_adapter=_adapt_search_clusters,
        ),
        "list_sales": Operation(
            client="reports",
            method="api_v1_supplier_sales_get",
            payload_adapter=_adapt_list_sales,
        ),
        "sales_funnel": Operation(
            client="analytics",
            method="post_v3_sales_funnel_products",
            payload_adapter=_adapt_sales_funnel,
        ),
        "search_queries": Operation(
            client="analytics",
            method="api_v2_search_report_report_post",
            payload_adapter=_adapt_search_queries,
        ),
        "stock_analytics": Operation(
            client="analytics",
            method="api_v2_stocks_report_offices_post",
            payload_adapter=_adapt_stock_analytics,
        ),
        "stock_products": Operation(
            client="analytics",
            method="api_v2_stocks_report_products_products_post",
            payload_adapter=_adapt_stock_products,
        ),
        "wb_warehouse_stocks": Operation(
            client="analytics",
            method="post_v1_stocks_report_wb_warehouses",
            payload_adapter=_adapt_wb_warehouse_stocks,
        ),
        "report_status": Operation(
            client="analytics",
            method="api_v2_nm_report_downloads_get",
            payload_adapter=_adapt_report_status,
        ),
        "balance": Operation(
            client="finances",
            method="get_v1_account_balance",
            payload_adapter=_require_empty_payload,
        ),
        "financial_documents": Operation(
            client="finances",
            method="get_v1_documents_list",
            payload_adapter=_adapt_financial_documents,
        ),
        "feedbacks": Operation(
            client="communications",
            method="api_v1_feedbacks_get",
            payload_adapter=_adapt_feedbacks,
        ),
        "questions": Operation(
            client="communications",
            method="api_v1_questions_get",
            payload_adapter=_adapt_questions,
        ),
        "chats": Operation(
            client="communications",
            method="api_v1_seller_chats_get",
            payload_adapter=_require_empty_payload,
        ),
        "chat_events": Operation(
            client="communications",
            method="api_v1_seller_events_get",
            payload_adapter=_adapt_chat_events,
        ),
        "create_campaign": Operation(
            client="promotion",
            method="adv_v2_seacat_save_ad_post",
            mutation=True,
            payload_adapter=_adapt_create_campaign,
        ),
        "start_campaign": Operation(
            client="promotion",
            method="adv_v0_start_get",
            mutation=True,
            payload_adapter=_adapt_campaign_id,
        ),
        "pause_campaign": Operation(
            client="promotion",
            method="adv_v0_pause_get",
            mutation=True,
            payload_adapter=_adapt_campaign_id,
        ),
        "stop_campaign": Operation(
            client="promotion",
            method="adv_v0_stop_get",
            mutation=True,
            payload_adapter=_adapt_campaign_id,
        ),
        "delete_campaign": Operation(
            client="promotion",
            method="adv_v0_delete_get",
            mutation=True,
            payload_adapter=_adapt_campaign_id,
        ),
        "rename_campaign": Operation(
            client="promotion",
            method="adv_v0_rename_post",
            mutation=True,
            payload_adapter=_adapt_rename_campaign,
        ),
        "update_bids": Operation(
            client="promotion",
            method="api_advert_v1_bids_patch",
            mutation=True,
            payload_adapter=_adapt_update_bids,
        ),
        "set_minus_phrases": Operation(
            client="promotion",
            method="adv_v0_normquery_set_minus_post",
            mutation=True,
            payload_adapter=_adapt_set_minus_phrases,
        ),
        "start_report": Operation(
            client="analytics",
            method="api_v2_nm_report_downloads_post",
            mutation=True,
            payload_adapter=_adapt_start_report,
        ),
        "reply_feedback": Operation(
            client="communications",
            method="api_v1_feedbacks_answer_post",
            mutation=True,
            payload_adapter=_adapt_reply_feedback,
        ),
        "reply_question": Operation(
            client="communications",
            method="api_v1_questions_patch",
            mutation=True,
            payload_adapter=_adapt_reply_question,
        ),
        "send_chat_message": Operation(
            client="communications",
            method="api_v1_seller_message_post",
            mutation=True,
            payload_adapter=_adapt_send_chat_message,
        ),
        "deposit_campaign_budget": Operation(
            client="promotion",
            method="adv_v1_budget_deposit_post",
            mutation=True,
            payload_adapter=_adapt_deposit_campaign_budget,
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
        "rates": rates.DefaultApi(
            rates.ApiClient(rates.Configuration(api_key={"HeaderApiKey": token}))
        ),
        "reports": reports.DefaultApi(
            reports.ApiClient(reports.Configuration(api_key={"HeaderApiKey": token}))
        ),
        "promotion": promotion.DefaultApi(
            promotion.ApiClient(
                promotion.Configuration(api_key={"HeaderApiKey": token})
            )
        ),
        "analytics": analytics.DefaultApi(
            analytics.ApiClient(
                analytics.Configuration(api_key={"HeaderApiKey": token})
            )
        ),
        "finances": finances.DefaultApi(
            finances.ApiClient(finances.Configuration(api_key={"HeaderApiKey": token}))
        ),
        "communications": communications.DefaultApi(
            communications.ApiClient(
                communications.Configuration(api_key={"HeaderApiKey": token})
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
            if operation.raw_json:
                response = _read_raw_json_response(response)
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
        reason = getattr(error, "reason", None)
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
        if (
            status == 0
            or isinstance(error, TimeoutError | ConnectionError | Urllib3HTTPError)
            or isinstance(reason, TimeoutError | ConnectionError | Urllib3HTTPError)
        ):
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
