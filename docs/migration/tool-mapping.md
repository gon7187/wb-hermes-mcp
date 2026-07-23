# Legacy WB endpoint to `wb` tool mapping

## Read paths

| Legacy endpoint | New explicit tool | Used by |
| --- | --- | --- |
| `GET /adv/v1/promotion/count` | `wb_get_campaign_counts` | stats cache |
| `GET /api/advert/v2/adverts` | `wb_list_campaigns`, `wb_get_campaign` | campaign workflows |
| `GET /adv/v3/fullstats` | `wb_get_campaign_stats` | cache, live totals, health |
| `GET /adv/v1/budget` | `wb_get_campaign_budget` | monitor, health |
| `GET /adv/v1/upd` | `wb_get_campaign_spend_history` | health, daily budget job |
| `POST /api/advert/v1/bids/min` | `wb_get_minimum_campaign_bids` | bid reference |
| `GET /api/v1/supplier/sales` | `wb_list_sales` | weekly GMV, dashboard |
| `POST /api/v2/stocks-report/products/products` | `wb_get_stock_products` | low-stock |
| `POST /api/analytics/v1/stocks-report/wb-warehouses` | `wb_get_wb_warehouse_stocks` | new-stock |
| `POST /content/v2/get/cards/list` | `wb_list_cards` | detector, campaign creation |

The old low-stock code named a different URL while sending the product-report
request body and reading product-report fields. Migration uses the matching SDK
operation rather than preserving that inconsistent literal URL.

The generated SDK omits `advertName` and daily `cpm` from fullstats. Scripts
join names from `wb_list_campaigns` and compute `cpm = spend / views * 1000`
when WB does not return it.

## Write paths

| Legacy operation | New plan path |
| --- | --- |
| create manual CPM campaign | `wb_plan_update_campaign`, `action=create` |
| start/pause/stop/delete/rename | `wb_plan_update_campaign` with explicit action |
| update bids | `wb_plan_update_bids` |
| update minus phrases | `wb_plan_update_minus_phrases` |
| deposit campaign budget | `wb_plan_deposit_campaign_budget` |

Plans do not call WB. They are single-use when explicitly applied. Migrated
cron scripts never apply plans automatically.

Budget deposits use base currency units (rubles for this account), have a
minimum of 1000, and default to source type `1` (balance). Bid fields named
`bid_kopecks` use minor currency units: 100 means one ruble.
