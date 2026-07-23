# WB Hermes MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a stdio MCP server that gives Hermes safe, GLM-readable access to the primary Wildberries seller workflows.

**Architecture:** A small Python package registers explicit business tools against FastMCP. Each tool delegates to a table-driven `WildberriesGateway`; the gateway creates generated SDK clients, validates request data, serializes SDK models, and normalizes failures. Mutations create a one-time in-memory confirmation plan and only `wb_apply_change` can execute it.

**Tech Stack:** Python 3.12+, `mcp[cli]>=1.27,<2` FastMCP, `wildberries-sdk`, Pydantic, pytest, uv.

## Global Constraints

- Runtime transport is stdio; no HTTP server, database, browser automation, or standalone CLI.
- All SDK access uses `wildberries-sdk`; do not hand-roll WB HTTP requests.
- API token comes only from `WB_API_TOKEN`; never log, test-fixture, commit, or print a real token.
- Reads execute immediately; every mutation is `plan → wb_apply_change` and confirmation expires after 15 minutes or one use.
- Cover account/tariffs, catalog, price/stock/warehouses, orders, supplies, promotion, analytics/reports, finance, and communications.
- Keep the tool set GLM-readable: explicit business names, concrete descriptions, JSON-object arguments, and no raw endpoint tool.
- Hermes entry uses the existing `mcp_servers.<label>.command/args/enabled/env` stdio schema.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Package metadata, runtime/test dependencies, ruff and pytest config. |
| `src/wb_mcp/__init__.py` | Package version. |
| `src/wb_mcp/__main__.py` | `python -m wb_mcp` stdio entry point. |
| `src/wb_mcp/gateway.py` | SDK client creation, operation registry, payload adaptation, JSON/error normalization. |
| `src/wb_mcp/changes.py` | Expiring, single-use confirmation plans. |
| `src/wb_mcp/server.py` | FastMCP server, explicit read/plan/apply tool registration. |
| `tests/test_changes.py` | Confirmation safety lifecycle. |
| `tests/test_gateway.py` | Dispatch, errors, serialization and SDK-token boundary. |
| `tests/test_server.py` | Tool inventory and representative tool flows from every business domain. |
| `README.md` | Installation, token setup, tool catalog, Hermes configuration and verification. |
| `deploy/hermes-wb-mcp.yaml.example` | Redacted sibling `mcp_servers.wb` configuration. |

## Tool inventory

Read tools: `wb_get_seller_profile`, `wb_get_tariffs`, `wb_list_cards`,
`wb_get_card_schema`, `wb_list_card_errors`, `wb_list_tags`, `wb_list_prices`,
`wb_get_stocks`, `wb_list_warehouses`, `wb_list_orders`,
`wb_get_order_details`, `wb_get_order_stickers`, `wb_list_supplies`,
`wb_get_supply`, `wb_get_supply_barcode`, `wb_list_campaigns`,
`wb_get_campaign`, `wb_get_campaign_stats`, `wb_get_campaign_bids`,
`wb_get_search_clusters`, `wb_get_sales_funnel`, `wb_get_search_queries`,
`wb_get_stock_analytics`, `wb_get_report_status`, `wb_get_balance`,
`wb_list_financial_documents`, `wb_list_feedbacks`, `wb_list_questions`, and
`wb_list_chats`.

Plan tools: `wb_plan_update_cards`, `wb_plan_save_media`,
`wb_plan_set_prices`, `wb_plan_set_stocks`, `wb_plan_manage_warehouse`,
`wb_plan_update_order_status`, `wb_plan_cancel_order`,
`wb_plan_create_supply`, `wb_plan_update_supply`, `wb_plan_update_campaign`,
`wb_plan_update_bids`, `wb_plan_update_minus_phrases`, `wb_plan_start_report`,
`wb_plan_reply_feedback`, `wb_plan_reply_question`, and
`wb_plan_send_chat_message`.

Control tools: `wb_describe_operation` and `wb_apply_change`.

### Task 1: Bootstrap a testable Python package

**Files:**
- Create: `pyproject.toml`
- Create: `src/wb_mcp/__init__.py`
- Create: `src/wb_mcp/__main__.py`
- Create: `tests/test_server.py`

**Interfaces:**
- Produces `wb_mcp.main() -> None`, which starts the stdio server.
- Produces an importable `wb_mcp.server.create_server(token: str | None = None)` factory.

- [ ] **Step 1: Write the failing import/entry-point test**

```python
from wb_mcp.server import create_server


def test_server_has_wb_name() -> None:
    assert create_server(token="test-token").name == "wb_mcp"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_server_has_wb_name -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'wb_mcp'`.

- [ ] **Step 3: Add the minimal package and dependency configuration**

```toml
[project]
name = "wb-hermes-mcp"
requires-python = ">=3.12"
dependencies = ["mcp[cli]>=1.27,<2", "wildberries-sdk==0.1.130"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# src/wb_mcp/__main__.py
from .server import main

main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_server_has_wb_name -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/wb_mcp tests/test_server.py uv.lock
git commit -m "feat: bootstrap WB MCP package"
```

### Task 2: Build the SDK gateway and confirmation store

**Files:**
- Create: `src/wb_mcp/gateway.py`
- Create: `src/wb_mcp/changes.py`
- Create: `tests/test_gateway.py`
- Create: `tests/test_changes.py`

**Interfaces:**
- Produces `WildberriesGateway(token: str, clients: Mapping[str, object] | None = None)`.
- Produces `WildberriesGateway.read(operation: str, payload: dict[str, object]) -> dict[str, object]`.
- Produces `WildberriesGateway.write(operation: str, payload: dict[str, object]) -> dict[str, object]`.
- Produces `ChangeStore.create(operation: str, payload: dict[str, object]) -> ChangePlan` and `consume(confirmation_id: str) -> ChangePlan`.

- [ ] **Step 1: Write failing safety and dispatch tests**

```python
from datetime import timedelta

import pytest

from wb_mcp.changes import ChangeStore, ConfirmationExpired, ConfirmationUsed
from wb_mcp.gateway import WildberriesGateway


def test_gateway_dispatches_a_read_to_registered_sdk_method() -> None:
    class General:
        def get_v1_seller_info(self):
            return {"name": "seller"}

    gateway = WildberriesGateway("token", clients={"general": General()})
    assert gateway.read("seller_profile", {}) == {"name": "seller"}


def test_confirmation_is_single_use() -> None:
    store = ChangeStore(ttl=timedelta(minutes=15))
    plan = store.create("set_prices", {"items": []})
    assert store.consume(plan.confirmation_id).operation == "set_prices"
    with pytest.raises(ConfirmationUsed):
        store.consume(plan.confirmation_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gateway.py tests/test_changes.py -v`

Expected: FAIL because `WildberriesGateway` and `ChangeStore` do not exist.

- [ ] **Step 3: Implement the gateway and change store**

```python
@dataclass(frozen=True)
class Operation:
    client: str
    method: str
    mutation: bool = False


class WildberriesGateway:
    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        return self._invoke(operation, payload, mutation=False)

    def write(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        return self._invoke(operation, payload, mutation=True)
```

`_invoke` must reject an unknown operation, enforce its read/mutation mode,
call only a registry-listed SDK method, recursively convert Pydantic models and
dataclasses to JSON-safe values, and turn SDK exceptions into `WBError` with
`operation`, `kind`, `message`, and `retryable` fields. `ChangeStore.consume`
must delete a valid plan before returning it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gateway.py tests/test_changes.py -v`

Expected: PASS, including expired and missing-confirmation cases.

- [ ] **Step 5: Commit**

```bash
git add src/wb_mcp/gateway.py src/wb_mcp/changes.py tests/test_gateway.py tests/test_changes.py
git commit -m "feat: add SDK gateway and confirmed writes"
```

### Task 3: Register catalog, inventory, order, and supply tools

**Files:**
- Modify: `src/wb_mcp/gateway.py`
- Modify: `src/wb_mcp/server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes `WildberriesGateway.read`, `WildberriesGateway.write`, and `ChangeStore`.
- Produces the 21 tools from the inventory above through `create_server`.

- [ ] **Step 1: Write failing representative-domain tests**

```python
@pytest.mark.anyio
async def test_server_exposes_catalog_order_and_supply_tools(client_session) -> None:
    result = await client_session.list_tools()
    names = {tool.name for tool in result.tools}
    assert {"wb_list_cards", "wb_get_stocks", "wb_list_orders", "wb_list_supplies"} <= names


@pytest.mark.anyio
async def test_plan_does_not_call_the_sdk_until_applied() -> None:
    calls: list[str] = []
    server = create_server(token="test-token", gateway=RecordingGateway(calls))
    async with create_connected_server_and_client_session(server, raise_exceptions=True) as client:
        plan = await client.call_tool("wb_plan_set_prices", {"payload": {"items": []}})
        assert calls == []
        await client.call_tool("wb_apply_change", {"confirmation_id": plan.structuredContent["confirmation_id"]})
    assert calls == ["set_prices"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -k 'catalog or plan' -v`

Expected: FAIL because listed tools and deferred execution are missing.

- [ ] **Step 3: Add operation metadata and explicit tool wrappers**

Implement the listed catalog, inventory, order and supply tool names as small
wrappers around `read_tool(operation, payload)` or `plan_tool(operation,
payload)`. Each description must say its WB scope, expected IDs/date filters,
and whether it returns paginated data or a confirmation plan. Map every wrapper
to a named generated SDK operation, never to a URL string.

- [ ] **Step 4: Run targeted tests**

Run: `uv run pytest tests/test_server.py -k 'catalog or order or supply or plan' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wb_mcp/gateway.py src/wb_mcp/server.py tests/test_server.py
git commit -m "feat: add catalog inventory orders and supplies tools"
```

### Task 4: Register promotion, analytics, finance, and communication tools

**Files:**
- Modify: `src/wb_mcp/gateway.py`
- Modify: `src/wb_mcp/server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes the gateway, change store and explicit wrapper helpers from Tasks 2–3.
- Produces all remaining tools from the inventory, plus `wb_describe_operation`.

- [ ] **Step 1: Write failing coverage and operation-description tests**

```python
@pytest.mark.anyio
async def test_server_exposes_every_business_domain(client_session) -> None:
    names = {tool.name for tool in (await client_session.list_tools()).tools}
    assert {"wb_list_campaigns", "wb_get_sales_funnel", "wb_get_balance", "wb_list_feedbacks"} <= names


def test_describe_operation_hides_sdk_internals() -> None:
    description = describe_operation("campaign_stats")
    assert description["tool"] == "wb_get_campaign_stats"
    assert "adv_v1" not in description["description"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -k 'business_domain or describe_operation' -v`

Expected: FAIL because those tools and descriptions are missing.

- [ ] **Step 3: Add explicit business tools and operation help**

Add promotion, analytics/report, finance and communication wrappers from the
inventory. `wb_describe_operation` accepts a public tool name and returns the
public description, required payload keys, examples with fake IDs, mutation
flag, and `plan_then_apply` guidance; it never returns client or method names.

- [ ] **Step 4: Run targeted tests**

Run: `uv run pytest tests/test_server.py -k 'business_domain or describe_operation or promotion or finance or feedback' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wb_mcp/gateway.py src/wb_mcp/server.py tests/test_server.py
git commit -m "feat: add promotion analytics finance and communication tools"
```

### Task 5: Document, package, deploy, and verify Hermes integration

**Files:**
- Create: `README.md`
- Create: `deploy/hermes-wb-mcp.yaml.example`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes `python -m wb_mcp` as a clean stdio process.
- Produces redacted Hermes configuration and reproducible verification commands.

- [ ] **Step 1: Write a failing stdio/tool-inventory test**

```python
@pytest.mark.anyio
async def test_tool_count_and_write_guards_are_visible(client_session) -> None:
    tools = (await client_session.list_tools()).tools
    assert len(tools) >= 45
    assert "wb_apply_change" in {tool.name for tool in tools}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_tool_count_and_write_guards_are_visible -v`

Expected: FAIL until all primary domain tools are registered.

- [ ] **Step 3: Add deployment artifact and operational documentation**

The README must contain `uv sync`, `WB_API_TOKEN` guidance without a value,
the exact virtualenv command Hermes will run, the complete public tool catalog,
the plan/apply example, and safe health checks. The YAML example must be:

```yaml
mcp_servers:
  wb:
    command: /opt/wb-mcp/.venv/bin/python
    args: ["-m", "wb_mcp"]
    enabled: true
    env:
      WB_API_TOKEN: "replace-on-vds-only"
```

- [ ] **Step 4: Run all static checks and tests**

Run: `uv run ruff check --fix src tests && uv run ruff format src tests && uv run pyright src && uv run pytest -v`

Expected: all commands exit 0.

- [ ] **Step 5: Deploy to VDS and perform the live read-only check**

Install the repository under `/opt/wb-mcp`, create its virtualenv with `uv`,
add the redacted `wb` stdio entry to `/root/.hermes/config.yaml` with the real
token only on the VDS, restart `hermes-gateway.service`, and verify:

```bash
systemctl is-active hermes-gateway.service
journalctl -u hermes-gateway.service -n 50 --no-pager
```

Then send MCP `initialize`, `tools/list`, and one harmless `wb_get_seller_profile`
call through Hermes. Do not execute a mutation during deployment verification.

- [ ] **Step 6: Commit**

```bash
git add README.md deploy/hermes-wb-mcp.yaml.example tests/test_server.py uv.lock
git commit -m "docs: add Hermes deployment guide"
```

## Plan self-review

- Scope coverage: Tasks 3–4 cover every domain named in the design; Task 2 enforces its token, error and confirmation invariants; Task 5 covers stdio/Hermes deployment and verification.
- Placeholder scan: every task has concrete files, commands and test behavior.
- Type consistency: all public tools consume `payload: dict[str, object]`; read wrappers call `WildberriesGateway.read`, plan wrappers call `ChangeStore.create`, and only `wb_apply_change` calls `WildberriesGateway.write`.
