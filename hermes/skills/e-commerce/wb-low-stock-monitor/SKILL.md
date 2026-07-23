---
name: wb-low-stock-monitor
description: Low-stock отчёт WB и безопасная подготовка планов паузы кампаний.
---

# WB low stock monitor

```bash
python3 /root/.hermes/scripts/wb_low_stock_monitor.py
```

Фактический фильтр:

- текущий остаток от 1 до 50 штук;
- кампания активна (`status=9`);
- рекламный расход за 7 дней не меньше 500 рублей.

Скрипт всегда только выводит отчёт и не принимает write-флаги.

Покажи пользователю все campaign ID, товары и недельный расход. Для выбранных
РК в живой сессии Hermes создай `wb_plan_update_campaign` с `action=pause`,
покажи summary, получи явное подтверждение и в той же MCP-сессии вызови
`wb_apply_change`. Confirmation ID process-local и не переносится между
процессами. После каждого применения проверь статус кампании read-вызовом.
