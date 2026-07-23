---
name: wb-seller-analytics
description: Аналитика продавца Wildberries через явные инструменты MCP wb и проверенные cron-скрипты.
---

# WB Seller Analytics

Используй только сервер `wb`. Не запрашивай у пользователя токен и не делай
прямые HTTP-вызовы.

## Основные источники

- карточки: `wb_list_cards`;
- текущие остатки WB: `wb_get_wb_warehouse_stocks`;
- товарный отчёт остатков: `wb_get_stock_products`;
- продажи: `wb_list_sales`;
- кампании: `wb_list_campaigns`, `wb_get_campaign_budget`;
- реклама: `wb_get_campaign_stats`, `wb_get_campaign_spend_history`;
- локальные сводки:
  `/root/.hermes/scripts/wb_adv_today_live.py`,
  `/root/.hermes/scripts/wb_budget_dashboard.py`,
  `/root/.hermes/scripts/wb_camp_health.py`.

Для расхода на рекламу всегда добавляй сегодняшний live-результат
`wb_adv_today_live.py`. Если API вернул ошибку или неполные данные, явно
пометь результат как частичный; не подгоняй цифры.

## Изменения

Любое изменение выполняется только так:

1. перечитать живой объект;
2. показать пользователю цель, значения и последствия;
3. получить явное подтверждение;
4. создать `wb_plan_*`;
5. применить ровно один раз через `wb_apply_change`;
6. проверить результат новым read-вызовом.

Пополнение бюджета — один запрос без автоматического ретрая. Создание,
пополнение и запуск кампании — три отдельные операции.

Подробности рекламных write-путей:
`references/wb-advert-write-api.md`.
