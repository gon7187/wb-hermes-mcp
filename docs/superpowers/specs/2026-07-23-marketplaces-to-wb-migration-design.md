# Hermes `marketplaces` to `wb` Migration Design

**Date:** 2026-07-23

**Status:** Approved for implementation by the user

## Goal

Remove the legacy Hermes MCP server `marketplaces` after every active
Wildberries automation uses the new `wb` MCP server and its observable
read-only results have been compared with the current production workflows.
No live Wildberries mutation is allowed during this migration.

## Scope

The migration covers:

- the active WB scripts under `/root/.hermes/scripts`;
- all WB skills and references that name `marketplaces`, its generic WB tools,
  or `/root/.marketplace-mcp/cabinets.json`;
- the seven active Hermes cron jobs that call those scripts or the old MCP;
- the Hermes MCP configuration and the user-memory pointer to the old token
  file;
- the alternate low-stock script under `/root/projects/wb_low_stock_fix`;
- documentation, automated tests, deployment checks, and a final dependency
  audit.

Generic mentions of online marketplaces, historical session logs, backups, and
finished reports are not migration targets. Ozon dependencies are audited
separately because the old server supports both WB and Ozon; the server is
removed only when no active Ozon caller still needs it.

## Architecture

### One credential boundary

`WB_API_TOKEN` remains readable only by `/opt/wb-hermes-mcp/run-wb-mcp`.
Migrated scripts must not read `cabinets.json`, accept a WB token as an
argument, or implement direct authenticated HTTP calls.

### A small persistent stdio client

`automation/wb_mcp_client.py` is a synchronous standard-library JSON-RPC
client. It starts the configured `wb` MCP command once per script process,
performs MCP initialization, calls named tools, returns `structuredContent`,
and closes the child cleanly.

This keeps cron entrypoints usable with system Python and avoids coupling them
to the MCP Python SDK installed inside the server virtual environment.
Importing the SDK gateway directly is rejected because it would bypass the MCP
boundary the migration is meant to establish.

### Stable automation contracts

Migrated scripts retain their current:

- command-line flags and safety defaults;
- stdout/stderr and exit-code behavior;
- JSON or Markdown result shapes;
- SQLite schema and state-file formats;
- inter-script files such as `/tmp/wb_new_items.json`.

Only the data source changes. Response-normalization functions isolate the
explicit `wb` tool schemas from each script's established output contract.

### Read and write paths

Read-only workflows may be called repeatedly against live WB data. Old and new
results are captured outside the public repository, normalized to a common
contract, and compared by identifiers, counts, totals, and business rules.
Time-sensitive comparisons use the same bounded time window where possible and
record tolerances when the upstream data can change between calls.

Write workflows call only `wb_plan_*` tools in tests or shadow checks.
`wb_apply_change` is never called during migration. Creation, pause, start,
deposit, and other mutations are verified with mocked MCP responses and plan
payload assertions.

## Repository Layout

- `automation/` — versioned MCP client, migrated scripts, and shared response
  normalization.
- `hermes/skills/` — sanitized, versioned copies of the migrated skill
  instructions and references.
- `deploy/migrate_hermes.py` — idempotent, targeted updates for the known cron
  jobs and Hermes config without replacing unrelated user configuration.
- `tests/` — MCP transport, response-contract, script, and migration tests.
- `docs/migration/` — inventory, endpoint/tool map, validation evidence, and
  rollback instructions. Raw production payloads are never committed.

## Cutover

1. Record the full active dependency inventory, including Ozon.
2. Capture old read-only baselines without mutating production state.
3. Add missing named `wb` tools through test-first changes.
4. Migrate scripts and skills and verify them locally.
5. Deploy in shadow mode and compare read-only live results.
6. Back up exact remote files, then switch scripts, skills, and cron jobs.
7. Run each safe scheduled workflow manually and inspect results.
8. Search active configuration again for legacy callers.
9. Remove `marketplaces`, restart Hermes, and prove `wb` plus the migrated
   workflows still work.

Rollback restores only the timestamped files changed by the deployment and
re-enables the old MCP entry. Existing databases and state files are preserved.

## Security and Acceptance

The migration is complete only when:

- no committed file contains a token or production response payload;
- no active WB script reads `cabinets.json` or calls WB HTTP directly;
- all affected skills and cron prompts name explicit `wb` tools;
- read-only contract comparisons pass or have a documented upstream reason;
- write-plan tests pass without a live mutation;
- a global active-state search finds no remaining need for `marketplaces`;
- `hermes mcp test wb`, the safe workflows, and the gateway service pass after
  the old server is removed.
