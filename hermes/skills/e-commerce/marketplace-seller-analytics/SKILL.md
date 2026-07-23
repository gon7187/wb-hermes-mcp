---
name: marketplace-seller-analytics
description: Унифицированный seller-анализ; для текущего кабинета используется Wildberries MCP wb.
---

# Seller Analytics

Для текущего кабинета используй только `wb`. Ozon-кабинет не настроен.

## Быстрый маршрут

- продажи и GMV: `wb_list_sales`;
- карточки: `wb_list_cards`;
- остатки: `wb_get_stock_products`, `wb_get_wb_warehouse_stocks`;
- кампании и бюджет: `wb_list_campaigns`, `wb_get_campaign_budget`;
- рекламная статистика: `wb_get_campaign_stats`;
- движения бюджета: `wb_get_campaign_spend_history`.

Не делай прямой HTTP fallback. При ошибке инструмента сообщи об ошибке и
используй только явно обозначенный локальный кэш.

Автоматизации:

- `/root/.hermes/scripts/wb_adv_today_live.py`;
- `/root/.hermes/scripts/wb_camp_monitor.py`;
- `/root/.hermes/scripts/wb_new_stock_detector.py`;
- `/root/.hermes/scripts/wb_low_stock_monitor.py`;
- `/root/.hermes/scripts/wb_create_camp.py`.

Write-пути всегда требуют plan → явное подтверждение → однократное применение
→ read-back. См. references.
