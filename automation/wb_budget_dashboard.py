#!/usr/bin/env python3
"""Build the established weekly WB advertising budget dashboard."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

try:
    from .wb_common import MCPCaller, as_float, call_with_retry, data_rows
    from .wb_mcp_client import WBMCPClient
except ImportError:  # pragma: no cover - direct deployment entrypoint
    from wb_common import (  # type: ignore[no-redef]
        MCPCaller,
        as_float,
        call_with_retry,
        data_rows,
    )
    from wb_mcp_client import WBMCPClient  # type: ignore[no-redef]

DEFAULT_DB = Path("/root/.hermes/data/wb_adv_stats.db")
BUDGET_PCT = 0.05
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def get_monday(day: date | None = None) -> date:
    selected = day or date.today()
    return selected - timedelta(days=selected.weekday())


def fetch_gmv_week(
    client: MCPCaller,
    start: date,
    end: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    result = call_with_retry(
        client,
        "wb_list_sales",
        {"date_from": f"{start.isoformat()}T00:00:00", "flag": 0},
        sleep=sleep,
    )
    gmv = 0.0
    for row in data_rows(result):
        sale_date = str(row.get("date", ""))[:10]
        sale_id = str(row.get("saleID", ""))
        if start.isoformat() <= sale_date <= end.isoformat() and not sale_id.startswith(
            "R"
        ):
            gmv += as_float(row.get("priceWithDisc"))
    return gmv


def get_ad_spend_week(
    db_path: str | Path,
    start: date,
    end: date,
) -> list[tuple[str, float]]:
    with sqlite3.connect(db_path) as connection:
        raw_rows = connection.execute(
            """
            SELECT date, ROUND(SUM(spend),0)
            FROM adv_daily
            WHERE date >= ? AND date <= ?
            GROUP BY date ORDER BY date
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [(str(day), float(spend)) for day, spend in raw_rows]


def bar(percent: float, width: int = 40) -> str:
    filled = int(width * min(percent, 1.0))
    return f"{'█' * filled}{'░' * (width - filled)} {percent * 100:.0f}%"


def fmt(number: float) -> str:
    return f"{number:,.0f} ₽".replace(",", " ")


def fmt_k(number: float) -> str:
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    return f"{number / 1000:.0f}К"


def build_report(
    *,
    gmv: float,
    spend_rows: list[tuple[str, float]],
    today: date,
) -> str:
    this_monday = get_monday(today)
    this_sunday = this_monday + timedelta(days=6)
    budget = gmv * BUDGET_PCT
    spend_by_day = dict(spend_rows)
    total_spent = sum(spend_by_day.values())
    days_passed = (today - this_monday).days + 1
    days_left = 7 - days_passed
    remaining = budget - total_spent
    daily_limit_avg = budget / 7
    daily_limit_remaining = remaining / max(days_left, 1)
    actual_avg = total_spent / max(days_passed, 1)
    percent = total_spent / budget if budget > 0 else 0
    projected = actual_avg * 7

    lines = [
        (
            f"📊 **Рекламный бюджет недели {this_monday.strftime('%d.%m')}–"
            f"{this_sunday.strftime('%d.%m')}**"
        ),
        "",
        f"GMV прошлой недели: {fmt(gmv)}",
        f"Бюджет (5%): **{fmt(budget)}**",
        f"Потрачено: **{fmt(total_spent)}**",
        "",
        "```",
        bar(percent),
        "```",
        "",
        f"{'✅' if remaining > 0 else '❌'} Остаток: **{fmt(remaining)}**",
        f"📅 Прошло: {days_passed}/7 дн | Осталось: {days_left} дн",
        f"📊 Лимит на день (средний): {fmt_k(daily_limit_avg)}",
        f"📊 Лимит на день (остаток): **{fmt_k(daily_limit_remaining)}**",
        f"📊 Фактический расход/день: {fmt_k(actual_avg)}",
    ]
    if projected > budget:
        lines.append(
            f"⚠️ Прогноз: **{fmt_k(projected)}** — перерасход "
            f"{fmt_k(projected - budget)}!"
        )
    else:
        lines.append(f"✅ Прогноз: {fmt_k(projected)} — в бюджете")
    lines.extend(["", "| День | Расход | vs лимит |", "|---|---|---|"])

    for index in range(7):
        day = this_monday + timedelta(days=index)
        spend = spend_by_day.get(day.isoformat(), 0)
        label = f"{WEEKDAYS[index]} {day.strftime('%d.%m')}"
        if day > today:
            lines.append(f"| {label} | — | — |")
            continue
        variance = (
            f"{(spend / daily_limit_avg - 1) * 100:+.0f}%"
            if daily_limit_avg > 0
            else "—"
        )
        if day == today:
            marker = "⬅️" if spend == 0 else ""
            lines.append(f"| {label} {marker} | {fmt_k(spend)} | {variance} |")
            continue
        marker = (
            "⚠️"
            if spend > daily_limit_avg * 1.1
            else "✅"
            if spend <= daily_limit_avg
            else ""
        )
        lines.append(f"| {label} | {fmt_k(spend)} | {variance} {marker} |")

    today_spend = spend_by_day.get(today.isoformat(), 0)
    if today <= this_sunday and today_spend > 0 and days_left > 0:
        lines.extend(
            [
                "",
                (
                    f"💡 Сегодня потрачено {fmt_k(today_spend)}, лимит остатка — "
                    f"{fmt_k(daily_limit_remaining)}/день"
                ),
            ]
        )
    return "\n".join(lines)


def main() -> int:
    try:
        today = date.today()
        this_monday = get_monday(today)
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)
        db_path = Path(os.getenv("WB_ADV_DB", str(DEFAULT_DB)))
        with WBMCPClient() as client:
            gmv = fetch_gmv_week(client, last_monday, last_sunday)
        spend_rows = get_ad_spend_week(db_path, this_monday, today)
        print(build_report(gmv=gmv, spend_rows=spend_rows, today=today))
        return 0
    except Exception as error:
        print(f"❌ Ошибка дашборда бюджета: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
