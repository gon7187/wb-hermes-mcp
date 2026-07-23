# WB MCP for Hermes — design

## Goal

Run a local stdio MCP server as a `wb` child process of Hermes on the VDS.
It uses `wildberries-sdk` rather than reimplementing Wildberries HTTP clients.
It covers the seller cabinet's primary workflows without exposing every generated
SDK endpoint to the model.

## Scope

The server exposes focused tools for these domains:

1. Account and tariffs: seller profile, rating, subscriptions, commission and logistics tariffs.
2. Catalog: cards, categories, characteristics, tags, media and card validation/errors.
3. Prices, discounts, stocks and warehouses.
4. Orders: FBS, DBW, DBS and click-and-collect lists, details, stickers and status flows.
5. Supplies: FBS and FBW supplies, acceptance, goods and packing places.
6. Promotion: campaigns, budget, bids, placements, NMs, search clusters, minus phrases and statistics.
7. Analytics and reports: sales funnel, search queries, stock/turnover data and asynchronous report exports.
8. Finance: balance, realization and payout documents.
9. Communications: feedback, questions, chats, claims and returns.

The first release deliberately omits low-level or administrative edge endpoints
that do not form a normal seller workflow, such as inviting/deleting seller
users. It does not claim to mirror the entire generated SDK API.

## Tool contract

About forty small, domain-named tools are registered, instead of a generic
`call_any_endpoint` tool or hundreds of generated methods. Read tools return
normalized JSON and paginate explicitly. Mutation tools are two phase:

1. `*_plan` validates the request against the SDK model and returns a short,
   redacted summary plus a one-time `confirmation_id`.
2. `wb_apply_change(confirmation_id)` performs exactly that stored request.

The confirmation expires after 15 minutes and is stored only in process memory.
No tool accepts an API token as an argument; the token comes from the process
environment (`WB_API_TOKEN`).

## Runtime

`python -m wb_mcp` is a stdio MCP process. Hermes receives a sibling entry:

```yaml
mcp_servers:
  wb:
    command: /opt/wb-mcp/.venv/bin/python
    args: ["-m", "wb_mcp"]
    enabled: true
    env:
      WB_API_TOKEN: "..."
```

The real secret is supplied only in Hermes's root-readable MCP `env` map,
not committed to the repository or copied into chat. A gateway restart starts
the new child process.

## Implementation shape

Keep one Python package with three modules:

- `server.py`: MCP registration and domain tool descriptions.
- `wb.py`: SDK client construction, normalized responses and pagination.
- `changes.py`: confirmation records and write execution.

The public tool functions call SDK clients directly. There is no custom HTTP
layer, database, job queue, web server or CLI product.

## Errors and safety

SDK validation errors, WB HTTP errors and rate limits become a compact,
actionable MCP error object containing the domain, operation and safe retry
hint. Token values and sensitive financial/customer fields are not logged.
Writes cannot run without a live confirmation record; a record can be consumed
once only.

## Verification

Tests use mocked SDK clients and cover: tool registration, pagination, token
absence, SDK error normalization, an expired confirmation, a one-time
confirmation and a representative read/write flow per domain. Deployment
verification is `initialize`, `tools/list`, one harmless account read, then
the Hermes gateway health check.

## Non-goals

- exposing every raw OpenAPI operation;
- browser automation, a standalone web service or a separate CLI;
- automatic price, budget or campaign changes without a confirmed plan.
