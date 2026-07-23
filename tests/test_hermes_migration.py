from __future__ import annotations

import copy
from pathlib import Path

from deploy.migrate_hermes import (
    DIRECT_MCP_JOB_IDS,
    patch_jobs,
    remove_legacy_server,
    update_user_memory,
)


FORBIDDEN = (
    "marketplaces",
    "wb_call_method",
    "wb_call_raw",
    "wb_get_adv_upd",
    "cabinets.json",
)


def test_versioned_skill_tree_has_every_migrated_file_and_no_legacy_calls() -> None:
    expected = {
        "analytics/wb-seller-analytics/SKILL.md",
        "analytics/wb-seller-analytics/references/wb-advert-write-api.md",
        "e-commerce/marketplace-seller-analytics/SKILL.md",
        "e-commerce/marketplace-seller-analytics/references/wb-api.md",
        "e-commerce/marketplace-seller-analytics/references/wb-advert-write-api.md",
        "e-commerce/marketplace-seller-analytics/references/wb-stocks-analytics.md",
        "e-commerce/wb-adv-stats-cache/SKILL.md",
        "e-commerce/wb-budget-dashboard/SKILL.md",
        "e-commerce/wb-budget-dashboard/references/daily-spend-forecast.md",
        "e-commerce/wb-camp-auto-fund/SKILL.md",
        "e-commerce/wb-camp-create/SKILL.md",
        "e-commerce/wb-low-stock-monitor/SKILL.md",
        "devops/hermes-mcp-setup/SKILL.md",
    }
    root = Path("hermes/skills")
    paths = {str(path.relative_to(root)) for path in root.rglob("*.md")}

    assert paths == expected
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*.md")
    ).lower()
    assert not [token for token in FORBIDDEN if token in rendered]


def test_job_patch_is_targeted_idempotent_and_preserves_unrelated_jobs() -> None:
    jobs = {
        "jobs": [
            {
                "id": "7f600e5714c0",
                "enabled_toolsets": ["marketplaces", "terminal", "file"],
                "prompt": (
                    "2. Получи отчёт по реализации через wb_call_method → "
                    "operation_id=wb_report_realization, query={...}\n"
                    "3. Из отчёта: GMV = Σ retail_price_withdisc_rub"
                ),
            },
            {
                "id": "c57ee9e2f113",
                "enabled_toolsets": ["marketplaces", "terminal", "file"],
                "prompt": (
                    "## Сбор данных (WB API через MCP marketplaces)\n"
                    "1. Вчерашний расход: wb_call_method → "
                    "operation_id=wb_get_adv_upd, query={...}"
                ),
            },
            {
                "id": "unrelated",
                "enabled_toolsets": ["marketplaces"],
                "prompt": "leave me unchanged",
            },
        ]
    }
    original_unrelated = copy.deepcopy(jobs["jobs"][2])

    assert patch_jobs(jobs) == 2
    assert patch_jobs(jobs) == 0

    direct = [job for job in jobs["jobs"] if job["id"] in DIRECT_MCP_JOB_IDS]
    assert all("marketplaces" not in job["enabled_toolsets"] for job in direct)
    assert all("wb" in job["enabled_toolsets"] for job in direct)
    assert all(
        not any(token in job["prompt"] for token in FORBIDDEN[:4]) for job in direct
    )
    assert jobs["jobs"][2] == original_unrelated


def test_config_removal_drops_only_the_exact_legacy_server_block() -> None:
    config = """mcp_servers:
  filesystem:
    command: fs
    enabled: true
  marketplaces:
    args:
      - marketplaces-mcp-ru
    command: uvx
    enabled: true
  wb:
    command: /opt/wb-hermes-mcp/run-wb-mcp
    enabled: true
platform_toolsets:
  cli:
    - hermes-cli
"""

    updated, changed = remove_legacy_server(config)

    assert changed is True
    assert "  marketplaces:" not in updated
    assert "marketplaces-mcp-ru" not in updated
    assert "  filesystem:" in updated
    assert "  wb:" in updated
    assert "platform_toolsets:" in updated
    assert remove_legacy_server(updated) == (updated, False)


def test_config_removal_stops_at_top_level_when_legacy_is_last_server() -> None:
    config = """mcp_servers:
  wb:
    command: wb
  marketplaces:
    command: legacy
platform_toolsets:
  cli:
    - hermes-cli
session_reset:
  schedule: daily
"""

    updated, changed = remove_legacy_server(config)

    assert changed is True
    assert "marketplaces:" not in updated
    assert "platform_toolsets:" in updated
    assert "session_reset:" in updated


def test_user_memory_replaces_only_the_secret_store_pointer() -> None:
    memory = "Профиль. WB-ключ в ~/.marketplace-mcp/cabinets.json. Остальное."

    updated, changed = update_user_memory(memory)

    assert changed is True
    assert "cabinets.json" not in updated
    assert "MCP `wb`" in updated
