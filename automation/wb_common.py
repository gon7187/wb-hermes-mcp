"""Shared response helpers for the versioned Hermes WB scripts."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

try:
    from .wb_mcp_client import MCPClientError, MCPToolError
except ImportError:  # pragma: no cover - direct deployment helper
    from wb_mcp_client import MCPClientError, MCPToolError  # type: ignore[no-redef]


class MCPCaller(Protocol):
    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]: ...


def call(
    client: MCPCaller,
    tool: str,
    payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    arguments = {"payload": dict(payload)} if payload is not None else {}
    return client.call_tool(tool, arguments)


def call_with_retry(
    client: MCPCaller,
    tool: str,
    payload: Mapping[str, object] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> dict[str, object]:
    """Retry sanitized transient WB failures without replaying mutations."""

    delays = {
        "rate_limited": 65.0,
        "service_unavailable": 15.0,
        "transport_error": 5.0,
    }
    for attempt in range(attempts):
        try:
            return call(client, tool, payload)
        except MCPToolError as error:
            delay = delays.get(error.kind)
            if not error.retryable or delay is None or attempt == attempts - 1:
                raise
            sleep(delay * (attempt + 1))
        except MCPClientError:
            if attempt == attempts - 1:
                raise
            restart = getattr(client, "restart", None)
            if callable(restart):
                restart()
            sleep(5.0 * (attempt + 1))
    raise AssertionError("unreachable")


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [mapping(item) for item in value if isinstance(item, Mapping)]


def data_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    return rows(result.get("data"))


def campaign_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    return rows(result.get("adverts"))


def nested_items(result: Mapping[str, object]) -> list[dict[str, object]]:
    return rows(mapping(result.get("data")).get("items"))


def as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    return default


def as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default
