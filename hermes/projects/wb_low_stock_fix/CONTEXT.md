# Low-stock monitor context

The deployed entrypoint is
`/root/projects/wb_low_stock_fix/wb_low_stock_monitor.py`. Keep it identical to
`automation/wb_low_stock_monitor.py` in this repository.

The script is read-only with respect to Wildberries:

1. `wb_get_stock_products` returns the current product-stock report.
2. Products with stock from 1 through 50 units are retained.
3. `wb_list_campaigns` returns active campaigns (`status=9`).
4. `nmId` is matched to campaign ID.
5. Seven-day campaign spend comes from
   `/root/.hermes/data/wb_adv_stats.db`, table `adv_daily`.
6. Only active campaigns with at least 500 rubles of spend are reported.

The script must not read a token file, send an Authorization header, or call WB
over direct HTTP. The token is available only inside MCP server `wb`.

The entrypoint never pauses a campaign and rejects write flags. If the user
confirms a pause, Hermes must perform
`wb_plan_update_campaign(action=pause) → wb_apply_change → read-back` through
one live MCP process because confirmation IDs are process-local.

Progress belongs on stderr. A successful cron run may be silent when there are
no candidates.
