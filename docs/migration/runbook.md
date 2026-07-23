# Hermes migration runbook

This runbook moves the known WB automation from the legacy `marketplaces`
server to `wb`. Keep the legacy server enabled until the shadow checks and
active-state audit pass.

## 1. Back up the active files

Create a root-only archive containing:

- `/root/.hermes/scripts`;
- the affected skill directories under `/root/.hermes/skills`;
- `/root/.hermes/cron/jobs.json`;
- `/root/.hermes/config.yaml`;
- `/root/.hermes/memories/USER.md`;
- `/root/projects/wb_low_stock_fix`.

Store it under `/root/.hermes/backups` with mode `600`. Do not copy the archive
or any token-bearing config into this repository.

## 2. Deploy the MCP package

Sync the repository to `/opt/wb-hermes-mcp` while excluding `.git`, virtual
environments, caches and `wb.env`. Preserve the existing server-only
`/opt/wb-hermes-mcp/wb.env`, then reinstall the package in its virtual
environment.

Verify:

```bash
hermes mcp test wb
systemctl restart hermes-gateway.service
systemctl is-active hermes-gateway.service
```

The test must discover 56 tools.

## 3. Deploy scripts and skills

Overlay, without deleting unrelated files:

```bash
rsync -a automation/ <host>:/root/.hermes/scripts/
rsync -a hermes/skills/ <host>:/root/.hermes/skills/
scp automation/wb_low_stock_monitor.py \
  <host>:/root/projects/wb_low_stock_fix/wb_low_stock_monitor.py
scp deploy/migrate_hermes.py <host>:/root/.hermes/scripts/
```

Use mode `755` for the eight entrypoint scripts and migration helper, and mode
`644` for `wb_common.py`, `wb_mcp_client.py`, and `__init__.py`.

Standalone scripts are read-only with respect to WB. Campaign creation writes a
proposal file only. Any actual write must execute `plan → explicit
confirmation → apply → read-back` through one live Hermes MCP process because
confirmation IDs are process-local.

## 4. Switch the known cron prompts

Preview and apply the targeted patch:

```bash
python3 /root/.hermes/scripts/migrate_hermes.py --dry-run
python3 /root/.hermes/scripts/migrate_hermes.py
python3 /root/.hermes/scripts/migrate_hermes.py --dry-run
```

The first preview should identify the two known direct-MCP jobs. The final
preview must report zero changes. Script-launching jobs do not need prompt
rewrites because their entrypoint paths are preserved.

## 5. Remove the legacy server

Search active config, jobs, scripts and skills for the exact server/tool names
and legacy token-store path. Exclude backups, logs, session captures and the
private migration evidence directory. Resolve every active hit first.

Then run:

```bash
python3 /root/.hermes/scripts/migrate_hermes.py --remove-legacy
systemctl restart hermes-gateway.service
```

Verify that `marketplaces` is absent from the configured MCP list, no
`marketplaces-mcp-ru` process exists, `wb` still discovers 56 tools, and the
read-only scripts still execute.

Do not delete `/root/.marketplace-mcp/cabinets.json` as part of this runbook.
Removing a credential file is a separate destructive action.

## Rollback

Stop the gateway, extract the pre-cutover archive at `/`, and start the service:

```bash
systemctl stop hermes-gateway.service
tar -xzf /root/.hermes/backups/<wb-marketplaces-cutover-archive>.tar.gz -C /
systemctl start hermes-gateway.service
systemctl is-active hermes-gateway.service
```

Then run `hermes mcp test marketplaces` and the old read-only scripts. The
archive contains secrets and must remain mode `600`.
