#!/usr/bin/env python3
"""Prepare read-only manual CPM campaign proposals for a live Hermes session."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

try:
    from .wb_common import (
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
        rows,
    )
    from .wb_mcp_client import WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_int,
        call_with_retry,
        campaign_rows,
        mapping,
        rows,
    )
    from wb_mcp_client import WBMCPClient  # type: ignore[no-redef]

DEFAULT_NEW_ITEMS = Path("/tmp/wb_new_items.json")
DEFAULT_REGISTRY = Path("/root/.hermes/data/wb_created_by_us.json")
DEFAULT_PROPOSALS = Path("/tmp/wb_campaign_proposals.json")


def _campaign_name(article: str, name: str, today: date) -> str:
    if article:
        return f"{article}_{name[:25].strip()}/{today.strftime('%d.%m')}"
    return name


def build_campaign_proposal(
    *,
    nm_id: int,
    name: str,
    article: str = "",
    today: date | None = None,
) -> dict[str, object]:
    selected_date = today or date.today()
    return {
        "action": "create",
        "name": _campaign_name(article, name, selected_date),
        "nm_ids": [nm_id],
        "bid_type": "manual",
        "payment_type": "cpm",
        "placement_types": ["search", "recommendations"],
    }


def list_live_campaigns(client: MCPCaller) -> list[dict[str, object]]:
    return campaign_rows(
        call_with_retry(client, "wb_list_campaigns", {"statuses": [4, 9, 11]})
    )


def check_duplicate(
    nm_id: int,
    live_campaigns: list[dict[str, object]],
    registry: Mapping[str, object],
) -> tuple[int, str] | None:
    for campaign in live_campaigns:
        for nm_setting in rows(campaign.get("nm_settings")):
            if as_int(nm_setting.get("nm_id")) == nm_id:
                return as_int(campaign.get("id")), "live-list"
    registered = mapping(registry.get(str(nm_id)))
    registered_id = as_int(registered.get("advertId"))
    if registered_id:
        return registered_id, "local-registry"
    return None


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
        for card in rows(response.get("cards")):
            if as_int(card.get("nmID")) != nm_id:
                continue
            variants = rows(card.get("variants"))
            first = variants[0] if variants else {}
            result[nm_id] = {
                "name": str(card.get("title") or first.get("title") or ""),
                "article": str(card.get("vendorCode") or first.get("vendorCode") or ""),
            }
            break
    return result


def _load_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _items_from_args(
    arguments: list[str], new_items_path: Path
) -> list[dict[str, object]]:
    if not arguments:
        return []
    if arguments[0] == "--from-detector":
        raw = _load_json(new_items_path, [])
        if not isinstance(raw, list):
            return []
        return [
            mapping(item)
            for item in raw
            if isinstance(item, Mapping) and as_int(mapping(item).get("total")) > 20
        ]

    items: list[dict[str, object]] = []
    for argument in arguments:
        try:
            items.append({"nmId": int(argument), "name": "", "article": ""})
        except ValueError:
            print(f"⚠️ Пропускаю невалидный nmId: {argument}")
    return items


def main() -> int:
    new_items_path = Path(os.getenv("WB_NEW_ITEMS", str(DEFAULT_NEW_ITEMS)))
    registry_path = Path(os.getenv("WB_CREATED_REGISTRY", str(DEFAULT_REGISTRY)))
    proposals_path = Path(os.getenv("WB_CAMPAIGN_PROPOSALS", str(DEFAULT_PROPOSALS)))
    items = _items_from_args(sys.argv[1:], new_items_path)
    if not sys.argv[1:]:
        print("Usage: wb_create_camp.py <nmId> [nmId2 ...] | --from-detector")
        return 1
    if not items:
        if sys.argv[1] == "--from-detector" and not new_items_path.exists():
            print("❌ Нет файла /tmp/wb_new_items.json. Запусти детектор сначала.")
            return 1
        print("Нет товаров для создания РК.")
        return 0

    with WBMCPClient() as client:
        missing = [
            as_int(item.get("nmId"))
            for item in items
            if not item.get("article") or item.get("article") == "?"
        ]
        cards = fetch_card_info(client, missing)
        for item in items:
            if (nm_id := as_int(item.get("nmId"))) in cards:
                item.update(cards[nm_id])

        print("Загружаю живые РК для проверки дублей...", file=sys.stderr)
        live_campaigns = list_live_campaigns(client)
        registry = mapping(_load_json(registry_path, {}))
        proposals: list[dict[str, object]] = []
        existing: list[dict[str, object]] = []
        for item in items:
            nm_id = as_int(item.get("nmId"))
            duplicate = check_duplicate(nm_id, live_campaigns, registry)
            if duplicate:
                existing.append(
                    {
                        "nmId": nm_id,
                        "advertId": duplicate[0],
                        "source": duplicate[1],
                    }
                )
                print(
                    f"⏭️ nmId {nm_id} — уже есть живая РК {duplicate[0]} "
                    f"({duplicate[1]}), пропускаю"
                )
                continue

            name = str(item.get("name") or "?")
            article = str(item.get("article") or "")
            payload = build_campaign_proposal(
                nm_id=nm_id,
                name=name,
                article=article,
            )
            proposals.append(
                {
                    "nmId": nm_id,
                    "name": name,
                    "article": article,
                    "payload": payload,
                    "preparedAt": datetime.now().astimezone().isoformat(),
                }
            )
            print(f"📋 nmId {nm_id} ({article[:30]}) — proposal готов")

    proposals_path.write_text(
        json.dumps(proposals, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("=" * 50)
    print(
        f"ИТОГО: подготовлено {len(proposals)}, пропущено (уже есть РК) {len(existing)}"
    )
    if proposals:
        print(
            "\n⚠️ Кампании ещё НЕ созданы, НЕ запущены и НЕ пополнены. "
            f"Payload сохранён в {proposals_path}. Создавай подтверждение и "
            "применяй только в одной живой MCP-сессии Hermes."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
