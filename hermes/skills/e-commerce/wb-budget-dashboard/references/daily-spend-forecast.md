# Daily spend forecast

Для текущего дня используй `wb_adv_today_live.py`. Для полных прошлых дней —
SQLite-кэш `adv_daily`. Движения бюджета проверяй через
`wb_get_campaign_spend_history`, остатки кампаний — через
`wb_get_campaign_budget`.

Прогноз недели:

```text
actual_average = week_to_date / elapsed_days
projection = actual_average * 7
remaining_daily_limit = (weekly_budget - week_to_date) / remaining_days
```

Частичный текущий день помечай явно. Не сравнивай его как полный день.
