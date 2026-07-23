#!/usr/bin/env python3
"""Idempotently switch the known Hermes WB jobs away from the legacy MCP."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

DIRECT_MCP_JOB_IDS = frozenset({"7f600e5714c0", "c57ee9e2f113"})


def _replace_prompt(job_id: str, prompt: str) -> str:
    lines = prompt.splitlines()
    result: list[str] = []
    for line in lines:
        if job_id == "7f600e5714c0" and (
            "wb_report_realization" in line or "wb_call_method" in line
        ):
            result.append(
                "2. Получи продажи через wb_list_sales с payload="
                '{"date_from":"YYYY-MM-DDT00:00:00","flag":0}; '
                "оставь строки только до конечной даты периода."
            )
            continue
        if job_id == "7f600e5714c0" and "retail_price_withdisc_rub" in line:
            result.append(
                "3. GMV = сумма priceWithDisc продаж минус сумма priceWithDisc "
                "возвратов; возвраты определяй по saleID с префиксом R."
            )
            continue
        if job_id == "c57ee9e2f113" and "WB API через MCP marketplaces" in line:
            result.append("## Сбор данных (WB API через MCP wb)")
            continue
        if job_id == "c57ee9e2f113" and (
            "wb_get_adv_upd" in line or "wb_call_method" in line
        ):
            prefix = line.split(".", 1)[0]
            if "Вчерашний расход" in line:
                result.append(
                    f"{prefix}. Вчерашний расход: wb_get_campaign_spend_history "
                    'с payload={"date_from":"<вчера>","date_to":"<вчера>"}. '
                    "Суммируй updSum по advertId."
                )
            else:
                result.append(
                    f"{prefix}. Расход за неделю: "
                    "wb_get_campaign_spend_history за понедельник → вчера. "
                    "Период не больше 31 дня."
                )
            continue
        result.append(line)
    return "\n".join(result)


def patch_jobs(document: MutableMapping[str, Any]) -> int:
    jobs = document.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Hermes jobs document has no jobs list")
    changed_jobs = 0
    for raw_job in jobs:
        if not isinstance(raw_job, MutableMapping):
            continue
        job_id = raw_job.get("id")
        if job_id not in DIRECT_MCP_JOB_IDS:
            continue
        changed = False
        toolsets = raw_job.get("enabled_toolsets")
        if isinstance(toolsets, list) and "marketplaces" in toolsets:
            raw_job["enabled_toolsets"] = [
                "wb" if toolset == "marketplaces" else toolset for toolset in toolsets
            ]
            changed = True
        prompt = raw_job.get("prompt")
        if isinstance(prompt, str):
            updated_prompt = _replace_prompt(str(job_id), prompt)
            if updated_prompt != prompt:
                raw_job["prompt"] = updated_prompt
                changed = True
        if changed:
            changed_jobs += 1
    return changed_jobs


def remove_legacy_server(config: str) -> tuple[str, bool]:
    lines = config.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"  marketplaces:\s*\n?", line)
        ),
        None,
    )
    if start is None:
        return config, False
    end = start + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.lstrip(" ")
        if stripped.strip():
            indentation = len(line) - len(stripped)
            if indentation <= 2:
                break
        end += 1
    return "".join(lines[:start] + lines[end:]), True


def update_user_memory(memory: str) -> tuple[str, bool]:
    updated = memory.replace(
        "WB-ключ в ~/.marketplace-mcp/cabinets.json",
        "WB-ключ доступен только через MCP `wb`",
    )
    updated = updated.replace(
        "~/.marketplace-mcp/cabinets.json",
        "MCP `wb` (прямого доступа к токену нет)",
    )
    return updated, updated != memory


def _atomic_write(path: Path, content: str) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobs",
        type=Path,
        default=Path("/root/.hermes/cron/jobs.json"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/root/.hermes/config.yaml"),
    )
    parser.add_argument(
        "--user-memory",
        type=Path,
        default=Path("/root/.hermes/memories/USER.md"),
    )
    parser.add_argument("--remove-legacy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    jobs = json.loads(arguments.jobs.read_text(encoding="utf-8"))
    changed_jobs = patch_jobs(jobs)
    outputs: list[tuple[Path, str]] = [
        (arguments.jobs, json.dumps(jobs, ensure_ascii=False, indent=2) + "\n")
    ]

    memory = arguments.user_memory.read_text(encoding="utf-8")
    updated_memory, memory_changed = update_user_memory(memory)
    outputs.append((arguments.user_memory, updated_memory))

    config_changed = False
    if arguments.remove_legacy:
        config = arguments.config.read_text(encoding="utf-8")
        updated_config, config_changed = remove_legacy_server(config)
        outputs.append((arguments.config, updated_config))

    if not arguments.dry_run:
        for path, content in outputs:
            _atomic_write(path, content)
    print(
        json.dumps(
            {
                "jobs_changed": changed_jobs,
                "memory_changed": memory_changed,
                "config_changed": config_changed,
                "dry_run": arguments.dry_run,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
