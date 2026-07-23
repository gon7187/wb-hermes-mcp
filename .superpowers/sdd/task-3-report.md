# Task 3 report — catalog, inventory, orders and supplies

## Implemented

- Registered all requested catalog, inventory, FBS order and FBS supply read tools,
  nine confirmation-plan tools, and `wb_apply_change` through FastMCP's public
  decorator API.
- Added strict Pydantic payload models (`extra='forbid'`) with Russian field
  descriptions and examples. Tool results are JSON dictionaries and carry
  read-only annotations appropriate to their execution behaviour.
- Extended the named SDK whitelist and adapters for the required `items` and
  `orders_fbs` generated clients. Request adapters reject unsupported fields
  before SDK dispatch.
- Plan tools validate through the gateway when available, create only an
  in-memory one-time confirmation, and never invoke `write`. `wb_apply_change`
  consumes a confirmation before the single write attempt.
- `create_server()` obtains `WB_API_TOKEN` only from the runtime environment
  when no explicit test token or injected gateway is supplied. No token value
  is stored or logged.

## Verification

- TDD RED: `uv run pytest tests/test_server.py -k 'catalog or plan or routes' -v`
  initially failed because the server did not accept an injected gateway or
  expose the requested tools.
- GREEN: the same focused suite passed (`3 passed`).
- Full suite: `uv run pytest -v` passed (`15 passed`).
- Static checks: `uv run ruff check --fix ...`, `uv run ruff format ...`, and
  `uv run pyright ...` completed with no errors.
- An additional official in-memory MCP session exercised all 13 read tools and
  all 9 plan/apply paths with an injected recording gateway: 13 reads and 9
  writes, with no Wildberries network call.

## Intentional SDK limits

- The installed SDK has no safe single-FBS-order GET by `order_id`.
  `wb_get_order_details` returns a structured validation response when an ID is
  supplied and directs the caller to paginated `wb_list_orders`; without an ID
  it uses the actual new-orders operation.
- The SDK exposes no generic editable supply fields. `wb_plan_update_supply`
  safely supports only adding/moving orders, delivery, and deletion.
- Stock reads require a seller `warehouse_id` plus explicit `chrt_ids`; there
  is no safe all-stock endpoint.
- Saving media replaces the entire media sequence, which is stated in the
  plan-tool description.

## Review remediation

- Replaced the misleading `wb_get_order_details` name with the read-only
  `wb_list_new_orders`; removed the fabricated status-update plan and added
  read-only `wb_get_order_statuses` backed by the real status endpoint.
- Added a `SafeFastMCP` input boundary that validates raw arguments before
  FastMCP can render invalid values, rejects root and nested extra fields, and
  returns a fixed structured validation error without echoing user input.
- Marked `wb_apply_change` as destructive, added a redacted exact plan summary,
  and made the price-upload gateway adapter reject unsupported fields directly.
- Added regression coverage for safe validation errors, one-time confirmation
  consumption on both successful and failed applies, redacted summaries,
  destructive annotations, named read-only order status access, and gateway
  operation validation.
- Verification: focused regression tests passed, full `uv run pytest -v`
  passed (`24 passed`), and Ruff formatting/lint plus Pyright completed cleanly.

## Surface correction

- The remediation removes the fabricated order-status write and the misleading
  single-order alias. The final Task 3 surface is 14 read tools, 8 plan tools,
  and the shared `wb_apply_change` control tool; `wb_list_new_orders` and
  `wb_get_order_statuses` are both read-only.
