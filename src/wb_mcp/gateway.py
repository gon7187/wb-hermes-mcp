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
from wildberries_sdk import general, items


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


OPERATIONS: Final[Mapping[str, Operation]] = MappingProxyType(
    {
        "seller_profile": Operation(
            client="general",
            method="get_v1_seller_info",
        ),
        "set_prices": Operation(
            client="items",
            method="api_v2_upload_task_post",
            mutation=True,
            payload_adapter=_adapt_price_upload,
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

    def _invoke(
        self,
        operation_name: str,
        payload: Mapping[str, object],
        *,
        mutation: bool,
    ) -> dict[str, object]:
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
