# Task 5 report — packaging, Hermes deployment and live verification

## Delivered

- Added a real subprocess stdio MCP test: it starts `python -m wb_mcp`,
  performs initialization and lists exactly 50 tools.
- Added a root-only `deploy/run-wb-mcp.sh` wrapper, redacted Hermes config
  example, deployment instructions and 10 Russian GLM tool-routing cases.
- Deployed the package to `/opt/wb-hermes-mcp` on the Hermes VDS, installed it
  in its own Python 3.12 virtual environment, and registered command
  `/opt/wb-hermes-mcp/run-wb-mcp` as MCP server `wb`.

## Live verification

- Hermes discovery found and enabled 50/50 tools for `wb`.
- A real read-only `wb_get_seller_profile` call through the deployed stdio
  wrapper completed successfully; the verifier printed only `READ_OK` and a
  field count, never seller data or credentials.
- `hermes-gateway.service` was restarted and is active; post-restart MCP test
  connected successfully.
- The token is kept only in `/opt/wb-hermes-mcp/wb.env` with mode `0600` and
  root ownership. A non-printing check confirmed that Hermes config contains
  no `WB_API_TOKEN` reference.

## Local verification

- Full suite: `uv run pytest -v` — 89 passed.
- Ruff lint/format, Pyright and ShellCheck completed cleanly.
