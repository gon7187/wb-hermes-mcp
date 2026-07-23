#!/usr/bin/env python3
"""Read-only campaign health report for decisions in a live Hermes session."""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

try:
    from .wb_common import (
        MCPCaller,
        as_float,
        as_int,
        call_with_retry,
        campaign_rows,
        data_rows,
        mapping,
    )
    from .wb_mcp_client import MCPClientError, WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_float,
        as_int,
        call_with_retry,
        campaign_rows,
        data_rows,
        mapping,
    )
    from wb_mcp_client import MCPClientError, WBMCPClient  # type: ignore[no-redef]

DEPOSIT_SUM = 3000
BUDGET_THRESHOLD = 1000
DRR_THRESHOLD = 15.0
STATS_DAYS = 7
MIN_WEEK_SPEND = 500


@dataclass(frozen=True)
class HealthResult:
    auto_fund: list[dict[str, object]]
    notify: list[dict[str, object]]
    junk: int


def collect_health(
    client: MCPCaller,
    *,
    today: date | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> HealthResult:
    selected_date = today or date.today()
    campaigns: list[dict[str, object]] = []
    for status in (9, 11):
        campaigns.extend(
            campaign_rows(
                call_with_retry(
                    client,
                    "wb_list_campaigns",
                    {"statuses": [status]},
                    sleep=sleep,
                )
            )
        )
        sleep(0.5)

    history = call_with_retry(
        client,
        "wb_get_campaign_spend_history",
        {
            "date_from": (selected_date - timedelta(days=14)).isoformat(),
            "date_to": selected_date.isoformat(),
        },
        sleep=sleep,
    )
    campaign_updates: defaultdict[int, list[tuple[float, str]]] = defaultdict(list)
    for item in data_rows(history):
        campaign_updates[as_int(item.get("advertId"))].append(
            (
                as_float(item.get("updSum")),
                str(item.get("updTime", ""))[:10],
            )
        )

    auto_topup: set[int] = set()
    for campaign_id, records in campaign_updates.items():
        if len(records) < 3:
            continue
        amount, count = Counter(record[0] for record in records).most_common(1)[0]
        distinct_dates = {day for value, day in records if value == amount}
        if count >= 3 and len(distinct_dates) >= 3:
            auto_topup.add(campaign_id)

    low_budget_ids: list[int] = []
    campaign_map: dict[int, dict[str, object]] = {}
    for index, campaign in enumerate(campaigns):
        campaign_id = as_int(campaign.get("id"))
        try:
            budget_result = call_with_retry(
                client,
                "wb_get_campaign_budget",
                {"campaign_id": campaign_id},
                sleep=sleep,
            )
        except MCPClientError:
            continue
        budget = as_int(budget_result.get("total"))
        campaign_map[campaign_id] = {
            "id": campaign_id,
            "name": str(mapping(campaign.get("settings")).get("name", "?")),
            "status": as_int(campaign.get("status")),
            "budget": budget,
            "auto": campaign_id in auto_topup,
        }
        if budget < BUDGET_THRESHOLD:
            low_budget_ids.append(campaign_id)
        if (index + 1) % 4 == 0:
            sleep(1)
    if not low_budget_ids:
        return HealthResult([], [], 0)

    statistics: dict[int, dict[str, object]] = {}
    batches = [
        low_budget_ids[index : index + 50]
        for index in range(0, len(low_budget_ids), 50)
    ]
    for index, batch in enumerate(batches):
        response = call_with_retry(
            client,
            "wb_get_campaign_stats",
            {
                "campaign_ids": batch,
                "date_from": (selected_date - timedelta(days=STATS_DAYS)).isoformat(),
                "date_to": selected_date.isoformat(),
            },
            sleep=sleep,
        )
        for item in data_rows(response):
            campaign_id = as_int(item.get("advertId"))
            spend = as_float(item.get("sum"))
            revenue = as_float(item.get("sum_price"))
            statistics[campaign_id] = {
                "spend": spend,
                "sum_price": revenue,
                "drr": spend / revenue * 100 if revenue > 0 else None,
                "orders": as_int(item.get("atbs")),
                "clicks": as_int(item.get("clicks")),
            }
        if index < len(batches) - 1:
            sleep(65)

    auto_fund: list[dict[str, object]] = []
    notify: list[dict[str, object]] = []
    junk = 0
    for campaign_id in low_budget_ids:
        campaign = campaign_map[campaign_id]
        stats = statistics.get(
            campaign_id,
            {
                "spend": 0.0,
                "sum_price": 0.0,
                "drr": None,
                "orders": 0,
                "clicks": 0,
            },
        )
        campaign.update(stats)
        if as_float(stats.get("spend")) < MIN_WEEK_SPEND:
            junk += 1
            continue
        drr = stats.get("drr")
        if campaign["auto"] and (drr is None or as_float(drr) <= DRR_THRESHOLD):
            auto_fund.append(campaign)
        else:
            notify.append(campaign)
    return HealthResult(auto_fund, notify, junk)


def format_report(
    result: HealthResult,
) -> str:
    status_names = {9: "активна", 11: "пауза", 7: "завершена", 4: "черновик"}
    lines: list[str] = []
    if result.junk:
        lines.append(
            f"🗑 Скрыто мёртвых РК (расход <{MIN_WEEK_SPEND}₽/нед): **{result.junk}**\n"
        )
    if result.auto_fund:
        lines.append(
            f"🤖 **АВТО-ПОПОЛНЕНИЕ** ({len(result.auto_fund)}) — "
            f"ДРР ≤{DRR_THRESHOLD:.0f}%\n"
        )
        for campaign in sorted(
            result.auto_fund,
            key=lambda item: as_float(item.get("drr"), 999),
        ):
            drr = campaign.get("drr")
            drr_text = (
                f"ДРР {as_float(drr):.1f}%" if drr is not None else "ДРР нет стат"
            )
            campaign_id = as_int(campaign.get("id"))
            lines.extend(
                [
                    (
                        f"• ID `{campaign_id}` | {campaign.get('budget', 0)}₽ "
                        f"→ +{DEPOSIT_SUM}₽ | {drr_text} | "
                        f"{status_names.get(as_int(campaign.get('status')), '?')}"
                    ),
                    f"  {str(campaign.get('name', '?'))[:55]}",
                ]
            )
        lines.append("")
    if result.notify:
        result.notify.sort(
            key=lambda item: as_float(item.get("drr"), 999),
            reverse=True,
        )
        lines.append(
            f"⚠️ **ТРЕБУЕТ ВНИМАНИЯ** ({len(result.notify)}) — пополни вручную\n"
        )
        for campaign in result.notify:
            drr = campaign.get("drr")
            drr_text = f"ДРР {as_float(drr):.1f}%" if drr is not None else "ДРР —"
            lines.extend(
                [
                    (
                        f"{'🤖' if campaign.get('auto') else '✋'} "
                        f"ID `{campaign.get('id')}` | {campaign.get('budget')}₽ | "
                        f"{drr_text} | "
                        f"{status_names.get(as_int(campaign.get('status')), '?')}"
                    ),
                    f"  {str(campaign.get('name', '?'))[:55]}",
                ]
            )
        lines.append("\n💡 Напиши «пополни РК <ID>» после проверки.")
    if result.auto_fund:
        lines.append(
            "\n🔒 Скрипт только читает данные. После подтверждения пользователя "
            "создай и примени пополнение в одной живой MCP-сессии Hermes."
        )
    return "\n".join(lines)


def main() -> int:
    if sys.argv[1:]:
        print(
            "Этот скрипт только читает данные; запись выполняется в живой "
            "MCP-сессии Hermes после подтверждения.",
            file=sys.stderr,
        )
        return 2
    try:
        with WBMCPClient() as client:
            result = collect_health(client)
            if not result.auto_fund and not result.notify:
                return 0
        print(format_report(result))
        return 0
    except MCPClientError as error:
        print(f"WB MCP error: {error}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
