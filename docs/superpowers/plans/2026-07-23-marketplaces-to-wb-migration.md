# Hermes `marketplaces` to `wb` Migration Implementation Plan

> Execute test-first. Never call `wb_apply_change` or run a legacy script with
> a mutating flag against live WB.

**Goal:** Preserve the outputs and safety behavior of the active Hermes WB
automations while replacing their old MCP/direct-token transport with the new
explicit `wb` MCP server, then remove `marketplaces`.

**Architecture:** A standard-library persistent MCP stdio client feeds
versioned automation scripts. Named server tools cover every required WB read
or write-plan operation. An idempotent deployment patch switches only the known
Hermes files and job IDs after live read-only equivalence checks.

**Tech stack:** Python 3.12, FastMCP, generated `wildberries-sdk`, pytest,
ruff, pyright, shellcheck, Hermes cron JSON.

---

### Task 1: Freeze the dependency and behavior inventory

**Files:**
- Create: `docs/migration/dependency-inventory.md`
- Create: `docs/migration/tool-mapping.md`
- Create: `docs/migration/validation.md`

1. Audit active WB and Ozon callers on the Hermes host, separating current
   configuration from backups, sessions, logs, and reports.
2. Record every legacy endpoint, input, output field, local-state side effect,
   and matching explicit `wb` tool.
3. Mark missing tools and removal blockers. Do not expose token values.
4. Capture the old read-only script outputs in a private temporary directory on
   the Hermes host; store only redacted summaries and comparison results in
   `validation.md`.

### Task 2: Add the automation MCP client test-first

**Files:**
- Create: `automation/__init__.py`
- Create: `automation/wb_mcp_client.py`
- Create: `tests/test_automation_client.py`

1. Write tests for initialization, tool calls, MCP errors, malformed stdout,
   child exit, timeout, structured-content extraction, and clean shutdown using
   a fake stdio server.
2. Run `uv run pytest tests/test_automation_client.py -v` and observe failure.
3. Implement the smallest synchronous JSON-RPC client that satisfies the
   tests. It must never log environment variables or request payloads on
   transport errors.
4. Run the targeted tests, ruff, format, and pyright on changed files.

### Task 3: Add missing named `wb` operations test-first

**Files:**
- Modify: `src/wb_mcp/gateway.py`
- Modify: `src/wb_mcp/server.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_distribution.py`
- Modify: `docs/tools.md`

1. For every gap in `tool-mapping.md`, write failing gateway-adapter and MCP
   schema/dispatch tests.
2. Add only explicit SDK-backed read operations and explicit write-plan
   operations needed by the audited workflows.
3. Exercise read tools against the live deployed server. Exercise write tools
   only through plan creation with a mocked gateway; never apply a plan.
4. Update the tool reference and routing metadata.

### Task 4: Migrate scripts while preserving contracts

**Files:**
- Create: `automation/wb_adv_stats_cache.py`
- Create: `automation/wb_adv_today_live.py`
- Create: `automation/wb_budget_dashboard.py`
- Create: `automation/wb_camp_health.py`
- Create: `automation/wb_camp_monitor.py`
- Create: `automation/wb_create_camp.py`
- Create: `automation/wb_low_stock_monitor.py`
- Create: `automation/wb_new_stock_detector.py`
- Create: `tests/test_automation_scripts.py`

1. Build redacted response fixtures from the legacy contracts and write failing
   tests for stdout, exit codes, SQLite rows, state transitions, and plan
   payloads.
2. Replace direct HTTP/token helpers with `wb_mcp_client` calls.
3. Preserve dry-run defaults. Mutation flags may create and print a plan but
   must not call `wb_apply_change`; applying remains an explicit interactive
   MCP action outside these cron scripts.
4. Run all automation tests plus formatting and type checks.

### Task 5: Migrate skill instructions and cron patching

**Files:**
- Create/modify: `hermes/skills/**`
- Create: `deploy/migrate_hermes.py`
- Create: `tests/test_hermes_migration.py`
- Modify: `README.md`

1. Write failing fixture tests proving the targeted skill tree and patched
   active jobs contain no `marketplaces`, `wb_call_method`, `wb_call_raw`,
   `wb_get_adv_upd`, or `cabinets.json` dependency.
2. Rewrite the eight affected skills and references around explicit `wb` tools
   and the migrated scripts. Remove contradictory automatic-funding guidance.
3. Implement an idempotent patcher for the seven known job IDs, the Hermes MCP
   entry, and the user-memory pointer while preserving unrelated content.
4. Document deployment, read-only validation, rollback, and the no-live-write
   rule.

### Task 6: Deploy shadow and compare live reads

**Files:**
- Modify: `docs/migration/validation.md`

1. Run the full local suite and static checks.
2. Deploy the package and migrated scripts to shadow paths on the Hermes host.
3. Call each new read path with the same bounded inputs as its legacy path.
4. Compare normalized identifiers, counts, totals, classifications, and output
   shape. Investigate every material mismatch before cutover.
5. Generate write plans only with non-production fixtures or mocked gateways.

### Task 7: Cut over and remove the old MCP

**Files:**
- Modify remotely after timestamped backup:
  `/root/.hermes/scripts/wb_*.py`, affected `/root/.hermes/skills/**`,
  `/root/.hermes/cron/jobs.json`, `/root/.hermes/config.yaml`,
  `/root/.hermes/memories/USER.md`, and the alternate low-stock script.

1. Back up the exact targeted files with restricted permissions.
2. Install the tested scripts and skill files and patch the seven jobs.
3. Restart Hermes and manually run every safe read-only workflow.
4. Audit active files again for legacy WB and Ozon dependencies.
5. If the audit is zero, remove `marketplaces`, restart Hermes, test `wb`, and
   rerun the safe workflows. If Ozon still actively depends on it, migrate that
   caller before removal rather than silently breaking it.
6. Preserve `cabinets.json` until a separate zero-consumer check proves it is
   unused; removing the MCP does not authorize deleting unrelated Ozon secrets.

### Task 8: Independent review, release, and GitHub push

1. Run `uv run pytest -v`, changed-file ruff/format/pyright, shellcheck, secret
   scanning, and `git diff --check`.
2. Request independent read-only reviews of behavior equivalence, safety, and
   the final active-state audit; address confirmed findings.
3. Commit intentional files, push `main`, and verify the public repository does
   not contain secrets or production data.
4. Record the deployed revision and final Hermes evidence in
   `docs/migration/validation.md`.
