#!/usr/bin/env python3
"""Detect products whose WB warehouse stock crossed the established threshold."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .wb_common import (
        MCPCaller,
        as_int,
        call_with_retry,
        mapping,
        nested_items,
    )
    from .wb_mcp_client import MCPClientError, WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_int,
        call_with_retry,
        mapping,
        nested_items,
    )
    from wb_mcp_client import MCPClientError, WBMCPClient  # type: ignore[no-redef]

DEFAULT_STATE = Path("/tmp/wb_stock_watch.json")
DEFAULT_NEW_ITEMS = Path("/tmp/wb_new_items.json")
MIN_QTY = 20


def collect_current_stocks(
    client: MCPCaller,
    *,
    limit: int = 250_000,
) -> dict[int, dict[str, object]]:
    current: dict[int, dict[str, object]] = {}
    offset = 0
    while True:
        result = call_with_retry(
            client,
            "wb_get_wb_warehouse_stocks",
            {"limit": limit, "offset": offset},
        )
        items = nested_items(result)
        for item in items:
            nm_id = as_int(item.get("nmId"))
            if not nm_id:
                continue
            stock = current.setdefault(
                nm_id,
                {"total": 0, "warehouses": {}, "type": ["FBO"]},
            )
            quantity = as_int(item.get("quantity"))
            stock["total"] = as_int(stock.get("total")) + quantity
            warehouse_name = str(item.get("warehouseName", "?"))
            warehouses = mapping(stock.get("warehouses"))
            warehouses[warehouse_name] = (
                as_int(warehouses.get(warehouse_name)) + quantity
            )
            stock["warehouses"] = warehouses
        if len(items) < limit:
            break
        offset += limit
    return current


def find_new_items(
    current: Mapping[int, Mapping[str, object]],
    previous: Mapping[str, object],
) -> list[dict[str, object]]:
    new_items: list[dict[str, object]] = []
    for nm_id, info in current.items():
        total = as_int(info.get("total"))
        previous_info = mapping(previous.get(str(nm_id)))
        if total > MIN_QTY and as_int(previous_info.get("total")) <= MIN_QTY:
            new_items.append(
                {
                    "nmId": nm_id,
                    "total": total,
                    "warehouses": mapping(info.get("warehouses")),
                }
            )
    return new_items


def fetch_card_info(
    client: MCPCaller,
    nm_ids: list[int],
) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for nm_id in nm_ids:
        response = call_with_retry(
            client,
            "wb_list_cards",
            {
                "settings": {
                    "cursor": {"limit": 5},
                    "filter": {"textSearch": str(nm_id), "withPhoto": -1},
                },
                "locale": "ru",
            },
        )
        cards = response.get("cards")
        if not isinstance(cards, list):
            continue
        for raw_card in cards:
            card = mapping(raw_card)
            if as_int(card.get("nmID")) != nm_id:
                continue
            variants = card.get("variants")
            first_variant = (
                mapping(variants[0]) if isinstance(variants, list) and variants else {}
            )
            result[nm_id] = {
                "name": str(card.get("title") or first_variant.get("title") or ""),
                "article": str(
                    card.get("vendorCode") or first_variant.get("vendorCode") or ""
                ),
            }
            break
    return result


def _load_previous(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return mapping(mapping(payload).get("stocks"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def format_notification(items: list[dict[str, object]]) -> str:
    lines = [
        (
            f"🆕 **{len(items)} "
            f"{'новый товар' if len(items) == 1 else 'новых товаров'} с остатком!**\n"
        )
    ]
    for item in items[:20]:
        warehouses = mapping(item.get("warehouses"))
        warehouse_text = ", ".join(
            f"{name}: {quantity}"
            for name, quantity in warehouses.items()
            if as_int(quantity) > 0
        )
        lines.extend(
            [
                f"📦 `{item.get('article', '?')}` (nmId: {item['nmId']})",
                f"   {str(item.get('name', '?'))[:80]}",
                f"   Остаток: **{item['total']} шт** ({warehouse_text})",
                "",
            ]
        )
    if len(items) > 20:
        lines.append(f"...и ещё {len(items) - 20}")
    lines.append(
        "\n💡 Напиши «создай РК» — подготовлю план создания без пополнения и запуска."
    )
    return "\n".join(lines)


def main() -> int:
    state_path = Path(os.getenv("WB_STOCK_STATE", str(DEFAULT_STATE)))
    new_items_path = Path(os.getenv("WB_NEW_ITEMS", str(DEFAULT_NEW_ITEMS)))
    try:
        with WBMCPClient() as client:
            print("Pulling FBO stocks...", file=sys.stderr)
            current = collect_current_stocks(client)
            print(
                f"FBO: {len(current)} nmId, "
                f"{sum(as_int(value.get('total')) for value in current.values())} units",
                file=sys.stderr,
            )
            previous = _load_previous(state_path)
            new_items = find_new_items(current, previous)
            card_info = fetch_card_info(
                client,
                [as_int(item.get("nmId")) for item in new_items],
            )
    except MCPClientError as error:
        print(f"WB MCP error: {error}", file=sys.stderr)
        return 0

    _write_json(
        state_path,
        {
            "timestamp": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
            "stocks": {str(nm_id): value for nm_id, value in current.items()},
        },
    )
    if not new_items:
        return 0

    enriched: list[dict[str, object]] = []
    for item in new_items:
        nm_id = as_int(item.get("nmId"))
        info = card_info.get(nm_id, {"name": "?", "article": "?"})
        enriched.append({**item, **info})
    _write_json(new_items_path, enriched)
    print(format_notification(enriched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
