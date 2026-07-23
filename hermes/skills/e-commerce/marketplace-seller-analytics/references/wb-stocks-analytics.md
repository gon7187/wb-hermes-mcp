# WB stock analytics

Используй два разных отчёта:

- `wb_get_wb_warehouse_stocks` — текущие количества по размерам и складам WB;
- `wb_get_stock_products` — товарные метрики за период, включая `stockCount`
  и `saleRate`.

Для детектора новых остатков запускай
`/root/.hermes/scripts/wb_new_stock_detector.py`. Он сохраняет совместимый
state в `/tmp/wb_stock_watch.json` и при переходе с `<=20` на `>20` создаёт
`/tmp/wb_new_items.json`.

Для low-stock запускай
`/root/.hermes/scripts/wb_low_stock_monitor.py`. По умолчанию он только
показывает товары с остатком `1..50`, активной кампанией и расходом не меньше
500 рублей за 7 дней. Флаг паузы создаёт планы, но не применяет их.
