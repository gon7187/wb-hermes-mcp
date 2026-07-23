---
name: wb-budget-dashboard
description: Утренний дашборд недельного рекламного бюджета WB.
---

# WB budget dashboard

```bash
python3 /root/.hermes/scripts/wb_budget_dashboard.py
```

Скрипт получает GMV прошлой недели через `wb_list_sales`, исключает возвраты
по `saleID`, берёт расход текущей недели из `wb_adv_stats.db` и выводит
Telegram Markdown:

- GMV;
- бюджет 5%;
- факт и остаток;
- средний и оставшийся дневной лимит;
- прогноз;
- таблицу семи дней.

При ошибке не подставляй вымышленные цифры. См.
`references/daily-spend-forecast.md`.
