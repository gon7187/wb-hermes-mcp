#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wb-hermes-mcp"
ENV_FILE="${APP_DIR}/wb.env"

if [[ ! -r "${ENV_FILE}" ]]; then
  echo "WB MCP environment file is unavailable." >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
. "${ENV_FILE}"
set +a

if [[ -z "${WB_API_TOKEN:-}" ]]; then
  echo "WB MCP token is unavailable." >&2
  exit 1
fi

exec "${APP_DIR}/.venv/bin/python" -m wb_mcp
