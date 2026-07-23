# Migration validation log

## Baseline

On 2026-07-23, old read-only workflows were captured under a restricted
server-only directory. Raw output is not committed.

| Workflow | Exit | stdout bytes | stderr bytes |
| --- | ---: | ---: | ---: |
| campaign monitor | 0 | 11300 | 0 |
| today advertising summary | 0 | 476 | 0 |
| budget dashboard | 0 | 938 | 0 |
| campaign health, dry-run | 0 | 0 | 139 |
| low-stock monitor, no pause | 0 | 0 | 220 |

The two empty stdout results were legitimate silent states for that live
snapshot, not proof of missing execution.

The nightly cache was not pointed at the production database during migration
testing. Its SQLite schema and insertion semantics are covered with an isolated
database fixture.

## Offline verification

- all required generated SDK methods exist in `wildberries-sdk==0.1.130`;
- six missing read operations and campaign deletion are registry-backed;
- `fullstats` uses the generated SDK raw-response method because the generated
  `appType` enum is older than the live WB response;
- deposit payload includes the explicit source and documented minimum;
- automation client tests cover initialization, structured results, errors,
  business errors, transient retries, malformed protocol data, child exit,
  timeout, and shutdown;
- script contract tests cover JSON, GMV, SQLite, state transitions, pause
  candidates and creation proposals;
- no migrated automation source reads a token store or implements an
  authorization header;
- standalone scripts contain no `wb_plan_*` or `wb_apply_change` calls.

## Live shadow

All raw output stayed in a mode-`700` server directory. Only normalized
comparisons are recorded here.

- Hermes connected to `wb` and discovered all 56 tools.
- Every newly added read tool returned a live response with the documented
  top-level structure.
- The budget dashboard was byte-for-byte identical to the old workflow.
- The campaign monitor preserved the JSON contract. Campaign/status drift
  between snapshots reconciled to the same total set.
- For today's advertising summary, the new snapshot was bracketed by old
  snapshots taken before and after it. Campaign count matched, growing totals
  were monotonic, and the new/control top ten matched completely.
- The isolated SQLite cache had identical schemas and all primary keys matched.
  Spend matched for every row; one row received normal late order/revenue
  attribution between the nightly and daytime snapshots.
- A repeated warehouse-stock snapshot matched the old source on product and
  unit totals. The detector's state-transition contract is also fixture-tested.
- The old low-stock script was silent because it sent a product-report body to
  the warehouse-report route. The SDK-backed replacement uses the correct
  product-stock operation and produced actionable read-only candidates.
- The old health script frequently lost `fullstats` batches by sleeping one
  second against a 20-second API interval. The replacement completed with
  rate-limit handling and produced a read-only report. No confirmation plan,
  deposit, start, pause, or other live write was executed.

## Cutover evidence

- The eight primary scripts, two shared client modules, thirteen skill/reference
  files, and the alternate low-stock copy were deployed from the repository.
- The two direct-MCP cron prompts were changed from `marketplaces` to `wb`; a
  second dry-run reported zero changes.
- The user memory no longer points agents at the legacy token store.
- Post-cutover dashboard output remained byte-identical; monitor, low-stock and
  detector scripts exited successfully through the deployed paths.
- A private rollback archive was created before the first file switch.

## Legacy removal

- The active-state audit found zero cron toolsets, prompt aliases, scripts,
  skills or project files dependent on the legacy server or token-store path.
  Backups, historical cron output, logs and session captures were excluded from
  the active-state decision and retained privately.
- The obsolete direct-HTTP helper and stale migration reference were moved to a
  root-only rollback directory after confirming that they had no active caller.
- The targeted config patch removed only `marketplaces`; its second dry-run
  reported no change.
- Hermes restarted successfully. Its MCP list no longer contains
  `marketplaces`, no legacy server process is running, and `wb` still discovers
  all 56 tools.
- After removal, dashboard, low-stock, detector and campaign-monitor entrypoints
  all exited successfully. The dashboard remained byte-identical and the
  monitor reported a complete, non-partial result.
- `/root/.marketplace-mcp/cabinets.json` was deliberately not deleted. It is no
  longer an active dependency, but credential-file deletion remains a separate
  destructive action.
