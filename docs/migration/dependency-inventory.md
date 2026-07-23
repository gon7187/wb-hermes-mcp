# Hermes legacy dependency inventory

Audit date: 2026-07-23. The audit distinguished active configuration from
backups, session transcripts, logs, completed reports, and unrelated uses of
the word “marketplace”.

## Active skills

Eight skills, thirteen files:

| Skill | Versioned migration files |
| --- | --- |
| `wb-seller-analytics` | `SKILL.md`, `references/wb-advert-write-api.md` |
| `marketplace-seller-analytics` | `SKILL.md`, three WB references |
| `wb-adv-stats-cache` | `SKILL.md` |
| `wb-budget-dashboard` | `SKILL.md`, `references/daily-spend-forecast.md` |
| `wb-camp-auto-fund` | `SKILL.md` |
| `wb-camp-create` | `SKILL.md` |
| `wb-low-stock-monitor` | `SKILL.md` |
| `hermes-mcp-setup` | `SKILL.md` |

The generic `web-scraping` skill is not a dependency and is intentionally not
changed.

## Active scripts

Eight production entrypoints under `/root/.hermes/scripts`:

| Script | Read/write behavior | Persistent contract |
| --- | --- | --- |
| `wb_adv_stats_cache.py` | read WB, write local cache | `wb_adv_stats.db`, silent cron success |
| `wb_adv_today_live.py` | read-only | one JSON summary line |
| `wb_budget_dashboard.py` | read-only | Telegram Markdown |
| `wb_camp_health.py` | read-only candidate report | Markdown; writes only in live Hermes MCP session |
| `wb_camp_monitor.py` | read-only | campaign/budget JSON |
| `wb_create_camp.py` | read-only preflight plus creation proposals | `/tmp/wb_campaign_proposals.json` |
| `wb_low_stock_monitor.py` | read-only candidate report | Markdown |
| `wb_new_stock_detector.py` | read WB, write local state | two established `/tmp` JSON files |

`wb_rate.py` was only the direct-HTTP helper for campaign creation and has no
role after migration. An alternate low-stock copy under
`/root/projects/wb_low_stock_fix` must receive the same migrated script.

Root-level sync scripts were false positives: they neither call the old MCP nor
read its token store.

## Active Hermes jobs

Seven enabled jobs:

| ID | Schedule | Dependency |
| --- | --- | --- |
| `99f52833ddbf` | daily 04:30 | advert cache script |
| `c33b3feb1b51` | daily 08:30 | budget dashboard script |
| `7f600e5714c0` | Monday 09:30 | direct GMV MCP prompt |
| `04e89644aea7` | weekdays 10:00, 15:00 | campaign monitor script |
| `c57ee9e2f113` | daily 10:30 | direct spend-history MCP prompt |
| `e2e6306f1d66` | weekdays 11:00, 16:00 | new-stock script |
| `52a240841322` | weekdays 11:30, 16:30 | low-stock script |

Only the two direct prompts need their enabled toolset changed. The five script
jobs retain their entrypoint names and schedules.

## Configuration and state

Active targets:

- `/root/.hermes/config.yaml`;
- `/root/.hermes/cron/jobs.json`;
- `/root/.hermes/memories/USER.md`;
- the local SQLite and JSON state named above.

The legacy secret file is not deleted as part of the MCP removal. Deleting
credentials requires a separate zero-consumer audit.

## Ozon audit

No active Ozon cron job, process, systemd unit, Hermes script, or configured
cabinet depends on the old server. Inactive source files and documentation
mention Ozon but do not block removal. Therefore, once the two WB prompts and
all WB scripts are switched, there is no active non-WB consumer of the legacy
MCP.
