---
name: wb-adv-stats-cache
description: Локальный SQLite-кэш рекламной статистики WB через MCP wb.
---

# WB advert stats cache

Ночной запуск:

```bash
python3 /root/.hermes/scripts/wb_adv_stats_cache.py
```

Скрипт использует `wb_get_campaign_counts`, `wb_list_campaigns` и
`wb_get_campaign_stats`. Он сохраняет прежние таблицы `adv_daily` и
`adv_status` в `/root/.hermes/data/wb_adv_stats.db`.

- успех cron: пустой stdout;
- ручной TTY: количество строк, кампаний и период;
- ошибка: stderr и exit 1.

Сегодняшние данные не находятся в ночном кэше. Для них запускай:

```bash
python3 /root/.hermes/scripts/wb_adv_today_live.py
```
